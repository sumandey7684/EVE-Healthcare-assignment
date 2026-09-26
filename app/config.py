from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "EVE Healthcare"
    environment: str = "development"
    debug: bool = False
    database_url: str = "postgresql+psycopg://eve:eve@localhost:5433/eve_healthcare"

    jwt_secret_key: str = Field(min_length=16)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    webhook_secret: str = Field(min_length=16)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
