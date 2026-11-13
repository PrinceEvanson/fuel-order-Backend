import os
import sys

from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .models import User
from .security import hash_password


def main() -> None:
    Base.metadata.create_all(engine)
    accounts = [
        ("client", os.environ.get("SEED_CLIENT_EMAIL", "client@demo.com"),
         os.environ.get("SEED_CLIENT_PASSWORD"), "Demo Client"),
        ("reviewer", os.environ.get("SEED_REVIEWER_EMAIL", "reviewer@demo.com"),
         os.environ.get("SEED_REVIEWER_PASSWORD"), "Demo CX Reviewer"),
    ]
    with SessionLocal() as db:
        for role, email, password, name in accounts:
            if not password:
                sys.exit(
                    f"Set SEED_{role.upper()}_PASSWORD in .env first (no default passwords).")
            if db.scalars(select(User).where(User.email == email.lower())).first():
                print(f"exists: {email}")
                continue
            db.add(User(email=email.lower(), name=name, role=role,
                   password_hash=hash_password(password)))
            print(f"created {role}: {email}")
        db.commit()


if __name__ == "__main__":
    main()
