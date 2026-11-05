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

    CORS_ORIGINS: list[str] = Field(default_factory=list)
    FILE_CLEANUP_DIR: Path = Field(default_factory=lambda: Path.home() / '.local/state/kms/file-cleanup')

    AI_ENABLED: bool = False
    YANDEX_AI_FOLDER_ID: str = ""
    YANDEX_AI_API_KEY: SecretStr = SecretStr("")
    AI_LLM_MODEL: str = "deepseek-v4.1-flash"
    AI_EMBED_DOC_MODEL: Literal["text-embeddings-v2-doc/latest"] = "text-embeddings-v2-doc/latest"
    AI_EMBED_QUERY_MODEL: Literal["text-embeddings-v2-query/latest"] = "text-embeddings-v2-query/latest"
    AI_EMBED_DIM: int = Field(default=256, ge=256, le=256)
    AI_TOP_K: int = Field(default=5, ge=5, le=5)
    AI_REQUEST_TIMEOUT_SECONDS: int = Field(default=120, ge=1, le=120)

    S3_ENDPOINT: str = "https://storage.yandexcloud.net"
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: SecretStr
    S3_BUCKET: str
    S3_REGION: str = "ru-central1"

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
