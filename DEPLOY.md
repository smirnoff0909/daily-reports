# Развёртывание

Памятка для системного администратора. Приложение внутреннее: инженеры
ежедневно записывают задачи и часы, руководитель смотрит месяц и выгружает Excel.
Команда — до нескольких десятков человек, нагрузка минимальная.

## Что нужно от сервера

- Linux с Docker и плагином Docker Compose (`docker compose version` должен отвечать).
- 1 CPU, 1 ГБ памяти, 10 ГБ диска — с запасом. Внешних сервисов и очередей нет.
- Свободные порты 80 и 443 на сервере.
- Имя в DNS, указывающее на сервер, — например `reports.company.ru`.
  Без домена приложение работает и по IP.
- Место для резервных копий **за пределами этого сервера**.

TLS настраивается на ваше усмотрение — сертификат приложение себе не выпускает,
см. раздел «Сертификат» ниже.

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
| `SITE_ADDRESS` | адрес, который слушает Caddy: `:80`, `http://reports.company.ru` или `reports.company.ru` — разница в разделе «Сертификат» |
| `SECRET_KEY` | сгенерированная строка сверху, никому не показывать |
| `POSTGRES_PASSWORD` | придумать длинный пароль |
| `POSTGRES_USER`, `POSTGRES_DB` | можно оставить `reports` |
| `APP_TIMEZONE` | `Europe/Moscow` — в этом поясе считается «сегодня» |
| `EDIT_WINDOW_DAYS` | `3` — сколько дней сотрудник правит свой отчёт |
| `COOKIE_SECURE` | `true`, если сайт открывается по https. **Для http поставить `false`**, иначе браузер не сохранит cookie и вход не сработает |

Запуск:

```bash
docker compose up -d --build
docker compose ps
curl -s localhost/healthz     # ожидается {"status":"ok"}
```

Миграции базы применяются автоматически при старте контейнера приложения,
руками ничего накатывать не нужно.

## Сертификат

Приложение сертификат не выпускает и ни на какой удостоверяющий центр не рассчитывает.
Как отдавать сайт — решаете вы. Три рабочих варианта:

**1. Без TLS, по http.** `SITE_ADDRESS=:80` или `SITE_ADDRESS=http://reports.company.ru`.
Обязательно `COOKIE_SECURE=false` в `.env`, иначе браузер не сохранит cookie сессии
и вход не сработает — ошибка при этом не показывается, просто не пускает.

**2. Свой сертификат** (корпоративный удостоверяющий центр, wildcard, самоподписанный).
Положить файлы рядом с `Caddyfile`, добавить в него строку `tls` и примонтировать
их в контейнер Caddy:

```
{$SITE_ADDRESS} {
	tls /etc/caddy/cert.pem /etc/caddy/key.pem
	encode zstd gzip
	reverse_proxy app:8000
	...
}
```

```yaml
# в docker-compose.yml, сервис caddy, к существующим volumes:
      - ./cert.pem:/etc/caddy/cert.pem:ro
      - ./key.pem:/etc/caddy/key.pem:ro
```

При этом `COOKIE_SECURE=true`.

**3. TLS на внешнем прокси** (nginx, балансировщик, корпоративный реверс-прокси).
Тогда `SITE_ADDRESS=:80`, Caddy отдаёт http внутрь периметра, `COOKIE_SECURE=true`,
а прокси должен передавать `X-Forwarded-Proto` — uvicorn запускается
с `--proxy-headers`, заголовок будет учтён.

**Осторожно с голым доменом.** Если написать `SITE_ADDRESS=reports.company.ru`
без схемы и без строки `tls`, Caddy попытается выпустить сертификат сам
и будет повторять попытки; при закрытом наружу сервере это не сработает,
а сайт может оказаться недоступным из-за переадресации на https.
Для http-варианта пишите схему явно: `http://reports.company.ru`.

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
