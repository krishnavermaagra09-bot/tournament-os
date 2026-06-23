import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Discord
    discord_token: str = ""
    discord_client_id: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://tournament:tournament_pass@localhost:5432/tournament_os"

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_db_url(cls, v: str) -> str:
        """
        Replit provides postgresql:// or postgres:// URLs.
        asyncpg needs postgresql+asyncpg:// and does NOT accept ?sslmode=.
        Strip sslmode from the query string; SSL is handled via connect_args in session.py.
        """
        if not isinstance(v, str):
            return v

        # Fix scheme
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://") and "+asyncpg" not in v:
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)

        # Strip sslmode — asyncpg uses ssl= kwarg, not a URL param
        if "sslmode=" in v:
            parsed = urlparse(v)
            params = parse_qs(parsed.query, keep_blank_values=True)
            params.pop("sslmode", None)
            new_query = urlencode({k: vv[0] for k, vv in params.items()})
            v = urlunparse(parsed._replace(query=new_query))

        return v

    # AI
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Web
    admin_dashboard_token: str = "change_me"
    secret_key: str = "change_me_secret"
    web_host: str = "0.0.0.0"
    web_port: int = 8000  # overridden at runtime by PORT env var (Railway/Render/Fly)

    @property
    def effective_port(self) -> int:
        """Return PORT if set by the platform, otherwise fall back to web_port."""
        return int(os.environ.get("PORT", self.web_port))

    # App
    environment: str = "development"
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"


settings = Settings()
