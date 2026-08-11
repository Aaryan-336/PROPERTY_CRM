from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://balaji_app:balaji_dev_pw@localhost:5432/balaji_crm"
    )
    migration_database_url: str = (
        "postgresql+psycopg://balaji_migrator:balaji_dev_pw@localhost:5432/balaji_crm"
    )

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
