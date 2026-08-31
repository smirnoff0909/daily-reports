"""Заведение и обслуживание учётных записей.

    python -m scripts.manage_users add --name "Иванов Иван" --login ivanov --role engineer
    python -m scripts.manage_users passwd --login ivanov
    python -m scripts.manage_users disable --login ivanov
    python -m scripts.manage_users list

Пароль вводится в скрытом режиме и нигде не сохраняется в открытом виде.
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.security import hash_password
from app.services.users import MIN_PASSWORD


def ask_password() -> str:
    first = getpass.getpass("Пароль: ")
    if len(first) < MIN_PASSWORD:
        sys.exit(f"Пароль короче {MIN_PASSWORD} символов — так нельзя.")
    if first != getpass.getpass("Повторите: "):
        sys.exit("Пароли не совпали.")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(description="Учётные записи")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="создать учётную запись")
    add.add_argument("--name", required=True)
    add.add_argument("--login", required=True)
    add.add_argument("--role", choices=["engineer", "manager"], default="engineer")

    passwd = sub.add_parser("passwd", help="сменить пароль")
    passwd.add_argument("--login", required=True)

    disable = sub.add_parser("disable", help="отключить доступ")
    disable.add_argument("--login", required=True)

    enable = sub.add_parser("enable", help="вернуть доступ")
    enable.add_argument("--login", required=True)

    sub.add_parser("list", help="показать всех")

    args = parser.parse_args()

    with SessionLocal() as db:
        if args.command == "list":
            for user in db.scalars(select(User).order_by(User.full_name)):
                state = "активен" if user.is_active else "отключён"
                print(f"{user.login:20} {user.full_name:30} {user.role:9} {state}")
            return

        if args.command == "add":
            if db.scalars(select(User).where(User.login == args.login)).first():
                sys.exit("Такой логин уже есть.")
            user = User(
                full_name=args.name,
                login=args.login,
                role=args.role,
                password_hash=hash_password(ask_password()),
            )
            db.add(user)
            db.commit()
            print(f"Создан: {user.login}")
            return

        user = db.scalars(select(User).where(User.login == args.login)).first()
        if user is None:
            sys.exit("Логин не найден.")

        if args.command == "passwd":
            user.password_hash = hash_password(ask_password())
            print("Пароль обновлён.")
        elif args.command == "disable":
            user.is_active = False
            print("Доступ отключён.")
        elif args.command == "enable":
            user.is_active = True
            print("Доступ возвращён.")
        db.commit()


if __name__ == "__main__":
    main()
