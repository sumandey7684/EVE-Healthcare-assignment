from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.config import settings
from app.errors import AppError

_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode("utf-8")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def verify_password_or_dummy(password: str, password_hash: str | None) -> bool:
    """Verify a password, using a dummy hash when the user is missing to reduce timing leaks."""
    if password_hash is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return False
    return verify_password(password, password_hash)


def create_access_token(
    user_id: UUID,
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload = {
        "sub": str(user_id),
        "iat": datetime.now(timezone.utc),
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> UUID:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except ExpiredSignatureError as exc:
        raise AppError(
            status_code=401,
            code="token_expired",
            message="Access token has expired.",
        ) from exc
    except InvalidTokenError as exc:
        raise AppError(
            status_code=401,
            code="invalid_token",
            message="Access token is invalid.",
        ) from exc

    subject = payload.get("sub")
    try:
        return UUID(str(subject))
    except (TypeError, ValueError) as exc:
        raise AppError(
            status_code=401,
            code="invalid_token",
            message="Access token is invalid.",
        ) from exc


def normalize_email(email: str) -> str:
    return email.strip().lower()
