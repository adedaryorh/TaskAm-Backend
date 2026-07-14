"""
Seed the first Admin user.

Usage:
    python -m app.scripts.seed_admin --phone +2348000000000 --password "changeme123" --name "TaskAm Admin"
"""
import argparse

from app.db.session import SessionLocal
from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


def seed_admin(phone_number: str, password: str, full_name: str) -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.phone_number == phone_number).first()
        if existing:
            print(f"User with phone {phone_number} already exists (role={existing.role.value}). Skipping.")
            return

        admin = User(
            phone_number=phone_number,
            password_hash=hash_password(password),
            full_name=full_name,
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        db.add(admin)
        db.commit()
        print(f"Admin user created: {phone_number}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    seed_admin(args.phone, args.password, args.name)
