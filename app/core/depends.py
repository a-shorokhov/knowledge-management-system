import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from core.config import settings
from core.exceptions import (
    AccountAccessDeniedException,
    AuthenticationRequiredException,
    InvalidTokenException,
)
from repositories.users import UserRepository

from adapters.file_storage.s3 import S3FileStorageAdapter
from adapters.file_cleanup_journal import FileCleanupJournal


def get_file_cleanup_journal():
    return FileCleanupJournal(settings.FILE_CLEANUP_DIR)

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="auth/login",
    auto_error=False,
)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    repository: UserRepository = Depends(),
):
    if not token:
        raise AuthenticationRequiredException()

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=[settings.TOKEN_ALGORITHM],
            options={"require": ["exp", "username", "user_id"]},
        )

        username = payload["username"]
        user_id = payload["user_id"]

        if not isinstance(username, str) or type(user_id) is not int:
            raise InvalidTokenException()

    except jwt.InvalidTokenError:
        raise InvalidTokenException() from None

    user = repository.get_user_by_username(username)

    if user is None or user["id"] != user_id:
        raise InvalidTokenException()

    return user


def require_user_owner(
    user_id: int,
    current_user: dict = Depends(get_current_user),
):
    if user_id != current_user["id"]:
        raise AccountAccessDeniedException()

    return current_user

def get_file_storage():
    storage = S3FileStorageAdapter(
        bucket_name=settings.S3_BUCKET,
        access_key=settings.S3_ACCESS_KEY,
        secret_key=settings.S3_SECRET_KEY.get_secret_value(),
        region_name=settings.S3_REGION,
        url=settings.S3_ENDPOINT,
    )

    try:
        yield storage
    finally:
        storage.client.close()
