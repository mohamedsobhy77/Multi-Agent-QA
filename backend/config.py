from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables or a .env file.

    Priority (highest → lowest):
      1. Real environment variables
      2. .env file in the working directory
      3. Default values defined here
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # silently drop unknown env vars
    )

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "QA Copilot"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    APP_PORT: int = 8000

    # ── PostgreSQL ─────────────────────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "qa_copilot"
    POSTGRES_PASSWORD: str = "qa_copilot_secret"
    POSTGRES_DB: str = "qa_copilot"

    # Connection pool
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20


    # ── OpenRouter ──────────────────────────────────────────────────────────────
    OPENROUTER_API_KEY: str = "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"
    OPENROUTER_MODEL: str = "openai/gpt-oss-120b:free"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"


    # ── Upload ─────────────────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 20

    # ── CORS ───────────────────────────────────────────────────────────────────
    # Stored internally as a list.
    # Accepts either a JSON array or a comma-separated string from the env:
    #   CORS_ORIGINS=http://localhost:3000,http://localhost:3001
    #   CORS_ORIGINS=["http://localhost:3000"]
    CORS_ORIGINS: str = "http://localhost:3000"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _coerce_cors_origins(cls, v: object) -> str:
        # Normalise to a single comma-separated string regardless of input type.
        if isinstance(v, list):
            return ",".join(str(o) for o in v)
        return str(v)

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS_ORIGINS as a parsed list (use this in middleware)."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # ── Computed properties ────────────────────────────────────────────────────

    @property
    def DATABASE_URL(self) -> str:
        """Async URL used by SQLAlchemy at runtime (asyncpg driver)."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Sync URL used by Alembic migrations (psycopg2 driver)."""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def MAX_UPLOAD_SIZE_BYTES(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    Using @lru_cache means the .env file is read exactly once per process.
    Call get_settings.cache_clear() in tests to reset between cases.
    """
    return Settings()


