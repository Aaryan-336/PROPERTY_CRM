import re
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Managed Postgres (Render, Heroku, Neon, Supabase) hands out URLs beginning
# `postgres://` or `postgresql://`. SQLAlchemy needs the driver named
# explicitly or it reaches for psycopg2, which is not installed here — the
# failure is an opaque ImportError at first connection, so normalize instead.
_PG_SCHEME = re.compile(r"^postgres(?:ql)?://")


def normalize_db_url(url: str) -> str:
    if not url:
        return url
    return _PG_SCHEME.sub("postgresql+psycopg://", url)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://balaji_app:balaji_dev_pw@localhost:5432/balaji_crm"
    )
    # Empty means "same as database_url". Local development uses a separate
    # migrator role that owns the tables (the app role deliberately has no DDL
    # rights); managed Postgres hands you a single owner role instead, and
    # requiring two URLs there would just mean setting the same value twice.
    migration_database_url: str = ""

    jwt_secret: str = "change-me-in-production-please-use-a-long-random-value"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 12

    # Capped pagination is a security control (SECURITY_MODEL.md §4): it bounds
    # how much of the client list any single request can return.
    max_page_size: int = 50
    default_page_size: int = 25
    list_rate_limit_per_minute: int = 60

    cors_origins: str = "http://localhost:3000"

    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:owner@balajicrm.local"

    # --- WhatsApp ingestion (Phase 3) ------------------------------------
    # Shared secret between the ingestion gateway and POST
    # /internal/whatsapp/ingest. That endpoint cannot use a JWT: the gateway is
    # a machine with no user identity, and minting it a staff account would put
    # a permanent credential for a human role on a box whose whole job is
    # holding an unofficial WhatsApp session (ARCHITECTURE.md §5 isolates it for
    # exactly that reason). Requests are HMAC-signed over the raw body instead.
    # Empty disables the endpoint entirely -- fail closed, so a deployment that
    # forgets to set it cannot be written to by anyone who finds the URL.
    whatsapp_ingest_secret: str = ""
    # Replay window for a signed request, in seconds.
    whatsapp_ingest_max_skew: int = 300

    # Model credentials for the extraction worker. Read by the SDK from the
    # environment; named here so `.env` is the single place to configure the
    # backend, and so ingestion-status can report whether it is set.
    anthropic_api_key: str = ""
    extraction_model: str = "claude-opus-5"
    extraction_effort: str = "low"

    @property
    def sqlalchemy_url(self) -> str:
        """Connection URL for the application role."""
        return normalize_db_url(self.database_url)

    @property
    def sqlalchemy_migration_url(self) -> str:
        """Connection URL migrations run as, falling back to the app role."""
        return normalize_db_url(self.migration_database_url or self.database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    @property
    def whatsapp_ingest_enabled(self) -> bool:
        return bool(self.whatsapp_ingest_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
