"""Application configuration via pydantic-settings.

All values are read from environment variables (see .env.example). Fields have
sensible local-compose defaults so the app boots without a full secret set.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: str = Field(default="development", alias="ENV")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@postgis:5432/floodwatch",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg://postgres:postgres@postgis:5432/floodwatch",
        alias="DATABASE_URL_SYNC",
    )

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE")

    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_jwt_secret: str = Field(default="", alias="SUPABASE_JWT_SECRET")
    supabase_service_role_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")

    h3_resolution: int = Field(default=8, alias="H3_RESOLUTION")

    earthdata_token: str = Field(default="", alias="EARTHDATA_TOKEN")
    openmeteo_base: str = Field(
        default="https://api.open-meteo.com/v1", alias="OPENMETEO_BASE"
    )
    gpm_imerg_base: str = Field(
        default="https://gpm1.gesdisc.eosdis.nasa.gov", alias="GPM_IMERG_BASE"
    )
    rainfall_refresh_cron: str = Field(
        default="*/30 * * * *", alias="RAINFALL_REFRESH_CRON"
    )

    model_path: str = Field(
        default="app/ml/artifacts/flood_model.pkl", alias="MODEL_PATH"
    )
    model_kind: str = Field(default="logistic", alias="MODEL_KIND")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
