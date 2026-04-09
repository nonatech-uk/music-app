from pathlib import Path

from pydantic import AliasChoices, Field

from mees_shared.settings import BaseAppSettings


class Settings(BaseAppSettings):
    db_host: str = Field("postgres", validation_alias=AliasChoices("db_host", "postgres_host"))
    db_name: str = "scrobble"
    db_user: str = Field("scrobble", validation_alias=AliasChoices("db_user", "postgres_user"))
    db_password: str = Field("", validation_alias=AliasChoices("db_password", "postgres_password"))
    db_sslmode: str = "prefer"
    api_port: int = 42010
    db_pool_min: int = 1
    db_pool_max: int = 5

    cors_origins: list[str] = [
        "https://music.mees.st",
        "http://localhost:5173",
    ]

    # Maloja-compat API key
    maloja_api_key: str = ""

    model_config = {
        "env_file": str(Path(__file__).resolve().parent / ".env"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()
