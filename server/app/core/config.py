"""Application configuration.

Every key here appears in ``deploy/.env.example`` with a placeholder and a comment.
See ``plan/features/foundation/design.md`` for the authoritative table.

The app refuses to start when ``SECRET_KEY`` is unset or still the example placeholder —
a deployment running on the documented placeholder secret would have forgeable sessions.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# server/app/core/config.py -> server/app/core -> server/app -> server -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / "deploy" / ".env"

#: The value shipped in ``deploy/.env.example``. Booting with this is refused.
SECRET_KEY_PLACEHOLDER = "generate-with-openssl-rand-hex-32"


class Settings(BaseSettings):
    """Runtime configuration, read from the environment and ``deploy/.env``."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Defaults are validated too, so an unset SECRET_KEY trips the validator below
        # rather than silently booting with "".
        validate_default=True,
    )

    # --- Database ---------------------------------------------------------
    postgres_user: str = "kindred"
    postgres_password: str = "change-me"
    postgres_db: str = "kindred"
    database_url: str = "postgresql+asyncpg://kindred:change-me@localhost:5432/kindred"

    # --- Security ---------------------------------------------------------
    secret_key: str = ""
    session_cookie_name: str = "kindred_session"
    session_ttl_hours: int = 720
    rate_limit_login_per_minute: int = 5

    # --- Seed -------------------------------------------------------------
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin"

    # --- Networking -------------------------------------------------------
    public_base_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173"

    # --- Google Maps Platform (two separate keys, per plan/architecture.md) --
    # Browser key: Maps JS + Places, restricted by HTTP referrer.
    google_maps_browser_key: str = ""
    # Server key: Geocoding, Distance Matrix, Directions, restricted by IP.
    google_maps_server_key: str = ""

    # --- Web Push (pwa-push) ----------------------------------------------
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.org"

    # --- Misc -------------------------------------------------------------
    attachments_dir: str = "/data/attachments"
    tz: str = "Europe/London"
    log_level: str = "info"

    app_version: str = Field(default="0.1.0", description="Reported by /api/v1/health")

    @field_validator("secret_key")
    @classmethod
    def _reject_placeholder_secret(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "SECRET_KEY is not set. Generate one with `openssl rand -hex 32` and put it "
                "in deploy/.env (see deploy/.env.example)."
            )
        if value.strip() == SECRET_KEY_PLACEHOLDER:
            raise ValueError(
                "SECRET_KEY is still the placeholder from deploy/.env.example. Generate a real "
                "one with `openssl rand -hex 32`: sessions signed with a published secret are "
                "forgeable."
            )
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        """``CORS_ORIGINS`` split into a list. Empty in production (same origin behind Caddy)."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Import this rather than instantiating ``Settings``."""
    return Settings()


#: Module-level singleton. Importing this module fails loudly when ``SECRET_KEY`` is missing
#: or is still the placeholder — that is deliberate: the app must refuse to boot.
settings: Settings = get_settings()
