from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        if authorization:
            raise AppError(
                status_code=401,
                code="invalid_token",
                message="Authorization header must use the Bearer scheme.",
            )
        raise AppError(
            status_code=401,
            code="missing_token",
            message="Authorization header is missing.",
        )
    if credentials.scheme.lower() != "bearer":
        raise AppError(
            status_code=401,
            code="invalid_token",
            message="Authorization header must use the Bearer scheme.",
        )

    user_id = decode_access_token(credentials.credentials)
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise AppError(
            status_code=401,
            code="user_not_found",
            message="The user for this token no longer exists.",
        )
    return user
