from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    db_host: str
    db_port: int = Field(ge=1, le=65535)
    db_user: str
    db_password: SecretStr
    db_name: str

    SECRET_KEY: SecretStr = Field(min_length=32)
    TOKEN_LIFETIME_MINUTES: int = Field(default=30, gt=0)
    TOKEN_ALGORITHM: Literal["HS256"] = "HS256"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


settings = Settings()

DB_URL = URL.create(
    "postgresql+psycopg2",
    username=settings.db_user,
    password=settings.db_password.get_secret_value(),
    host=settings.db_host,
    port=settings.db_port,
    database=settings.db_name,
)
