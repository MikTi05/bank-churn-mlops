"""Application settings loaded from environment variables and an optional .env file."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_path: str = "artifacts/model.joblib"
    database_url: str | None = None
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
