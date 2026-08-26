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

    # How a session ends, in two independent numbers rather than one.
    #
    # `idle` is the token's own lifetime, and it is renewed whenever the app is
    # used, so it measures *silence*: put the phone down for this long and you
    # sign in again. `absolute` is measured from the moment the password was
    # typed and is never extended, so a session cannot become permanent however
    # much it is used -- which is the whole reason a sliding session is safe to
    # make this long.
    #
    # Thirty days of silence is longer than any holiday an agent takes; ninety
    # days is a quarterly re-authentication. Shorten both on a shared device.
    session_idle_days: int = 30
    session_absolute_days: int = 90

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
    groq_api_key: str = ""
    # One model name, or several separated by commas and tried in order.
    #
    # Groq retires model names on a fairly short cycle, so treat this as a
    # setting to check when extraction starts 404ing, not a constant. The list
    # form exists for a different reason: Groq's allowances are *per model*, so
    # a second and third name are a second and third bucket rather than a
    # fallback of last resort. Empty falls back to extraction.DEFAULT_MODEL.
    extraction_model: str = ""
    # auto | json_schema | json_object. "auto" asks for a strict schema and
    # downgrades itself if the model will not honour one.
    extraction_schema_mode: str = "auto"

    # Run the extraction loop inside the API process instead of as its own
    # service.
    #
    # Extraction is a separate worker by design -- it is slow, it talks to a
    # third party, and it should not be able to stall a request. But Render does
    # not offer Background Workers on the free plan, so on that deployment there
    # is nowhere for the worker to live, and messages arrive and sit as
    # `pending` for ever: the feed looks connected and produces no inventory.
    #
    # Safe to run alongside a real worker. `claim_pending` takes its batch with
    # SELECT ... FOR UPDATE SKIP LOCKED, so two extractors divide the queue
    # rather than duplicating it.
    #
    # Off by default: a firm on a paid plan should run the worker properly,
    # where it can be restarted and scaled without bouncing the API.
    extraction_in_api: bool = False

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
