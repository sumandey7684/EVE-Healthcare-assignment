from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import User
from app.schemas.user import UserSignupRequest
from app.security import hash_password, normalize_email, verify_password_or_dummy


def register_user(db: Session, payload: UserSignupRequest) -> User:
    email = normalize_email(payload.email)
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise AppError(
            status_code=409,
            code="duplicate_email",
            message="An account with this email already exists.",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            status_code=409,
            code="duplicate_email",
            message="An account with this email already exists.",
        ) from exc
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    normalized_email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == normalized_email))
    password_hash = user.password_hash if user is not None else None
    if user is None or not verify_password_or_dummy(password, password_hash):
        raise AppError(
            status_code=401,
            code="invalid_credentials",
            message="Invalid email or password.",
        )
    return user
