from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, field_validator

# Raiz del repositorio: resuelve desde backend/app/core/config.py
# (config.py -> core -> app -> backend -> raiz del proyecto)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Configuracion de la aplicacion, cargada desde variables de entorno."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432

    @property
    def database_url(self) -> str:
        """URL de conexion a PostgreSQL usando el driver psycopg (v3)."""
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


class AuthSettings(BaseSettings):
    """Independent of DB settings: Alembic does not need JWT credentials."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env", env_file_encoding="utf-8",
        extra="ignore", hide_input_in_errors=True,
    )
    JWT_SECRET: SecretStr
    JWT_ACCESS_TOKEN_MINUTES: int = Field(default=15, gt=0)
    JWT_ISSUER: str = Field(default="red-antiextorsion-preventiva", min_length=1)
    JWT_AUDIENCE: str = Field(default="red-antiextorsion-api", min_length=1)

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret.encode("utf-8")) < 32 or not secret.strip():
            raise ValueError("JWT_SECRET requires at least 32 bytes of random secret material")
        return value


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
