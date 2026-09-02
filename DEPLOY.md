# Развёртывание

Памятка для системного администратора. Приложение внутреннее: инженеры
ежедневно записывают задачи и часы, руководитель смотрит месяц и выгружает Excel.
Команда — до нескольких десятков человек, нагрузка минимальная.

## Что нужно от сервера

- Linux с Docker и плагином Docker Compose (`docker compose version` должен отвечать).
- 1 CPU, 1 ГБ памяти, 10 ГБ диска — с запасом. Внешних сервисов и очередей нет.
- Свободные порты 80 и 443 на сервере.
- Имя в DNS, указывающее на сервер, — например `reports.company.ru`.
  Без домена приложение работает и по IP, но тогда не будет сертификата (см. ниже).
- Доступ наружу к Let's Encrypt по 443, если нужен автоматический сертификат.
- Место для резервных копий **за пределами этого сервера**.

Что поднимется: три контейнера — `postgres:16-alpine`, приложение на
`python:3.12-slim` (FastAPI + uvicorn) и `caddy:2-alpine` как обратный прокси.
Образ приложения собирается на сервере из `Dockerfile`, ничего скачивать
из приватных реестров не нужно.

## Установка

```bash
git clone https://github.com/smirnoff0909/daily-reports.git /opt/daily-reports
cd /opt/daily-reports
git checkout stable          # ветка stable — рабочая версия

cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # в SECRET_KEY
```

Заполнить `.env`:

| Переменная | Значение |
| --- | --- |
| `SITE_ADDRESS` | `reports.company.ru` — Caddy сам получит сертификат Let's Encrypt. Без домена оставить `:80` |
| `SECRET_KEY` | сгенерированная строка сверху, никому не показывать |
| `POSTGRES_PASSWORD` | придумать длинный пароль |
| `POSTGRES_USER`, `POSTGRES_DB` | можно оставить `reports` |
| `APP_TIMEZONE` | `Europe/Moscow` — в этом поясе считается «сегодня» |
| `EDIT_WINDOW_DAYS` | `3` — сколько дней сотрудник правит свой отчёт |
| `COOKIE_SECURE` | `true` для https. **Если сайт по http без сертификата — поставить `false`**, иначе браузер не сохранит cookie и вход не сработает |

Запуск:

```bash
docker compose up -d --build
docker compose ps
curl -s localhost/healthz     # ожидается {"status":"ok"}
```

Миграции базы применяются автоматически при старте контейнера приложения,
руками ничего накатывать не нужно.

## Учётные записи

База поднимается пустой. Первым заводится руководитель, дальше он добавляет
людей сам через веб-интерфейс, раздел «Сотрудники».

```bash
docker compose exec app python -m scripts.manage_users add \
  --name "Немчинов Лев" --login nemchinov --role manager
```

Пароль спрашивается интерактивно и не остаётся в истории команд.
Другие команды скрипта: `passwd`, `disable`, `enable`, `list`.

## Резервные копии

`scripts/backup.sh` делает `pg_dump`, сжимает его и удаляет копии старше 30 дней.
В cron:

```
0 2 * * * cd /opt/daily-reports && ./scripts/backup.sh >> /var/log/daily-reports-backup.log 2>&1
```

Копии обязательно переносить за пределы сервера — иначе они умрут вместе с диском.

## Обновление версии

```bash
cd /opt/daily-reports
git pull
docker compose up -d --build
```

Миграции применятся при старте. Перед обновлением снять резервную копию.

## Обслуживание

```bash
docker compose logs -f app        # логи приложения
docker compose restart app        # перезапуск
docker compose down               # остановить всё (данные в томах сохраняются)
```

Данные лежат в docker-томах `db-data` (база), `caddy-data` и `caddy-config`
(сертификаты). При `docker compose down` они не удаляются; `down -v` их сотрёт.

## Чего в приложении нет

Регистрации, восстановления пароля по почте, интеграций и фоновых задач.
Один процесс, одна база. Пароли — argon2, сессия в подписанной cookie.
