"""Bootstrap admin pertama: uv run python -m app.cli create-admin <username> --name "..."."""

import argparse
import getpass
import sys

from sqlalchemy import text

from app.auth import hash_password
from app.db import engine


def create_admin(username: str, name: str, password: str, force: bool) -> None:
    with engine.begin() as db:
        if not force and db.scalar(text("select 1 from user_roles where role = 'ADMIN' limit 1")):
            sys.exit("Admin sudah ada. Pakai --force untuk menambah admin lain.")
        user_id = db.scalar(
            text("""
            insert into users (username, password_hash, display_name)
            values (:u, :h, :n) returning id
            """),
            {"u": username, "h": hash_password(password), "n": name},
        )
        db.execute(
            text("insert into user_roles (user_id, role) values (:id, 'ADMIN')"), {"id": user_id}
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin")
    p.add_argument("username")
    p.add_argument("--name", required=True)
    p.add_argument("--force", action="store_true")
    args = parser.parse_args()

    password = getpass.getpass("Kata sandi admin (min. 12 karakter): ")
    if len(password) < 12:
        sys.exit("Kata sandi terlalu pendek.")
    if getpass.getpass("Ulangi kata sandi: ") != password:
        sys.exit("Kata sandi tidak sama.")
    create_admin(args.username, args.name, password, args.force)
    print(f"Admin '{args.username}' dibuat.")


if __name__ == "__main__":
    main()
