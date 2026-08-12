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

    # --- Map suggestions ---------------------------------------------------
    # Named settings rather than literals in a query (`map-suggestions/tasks.md` Phase 4): both
    # are product judgements about geography, and burying either in a `WHERE` clause is how a
    # threshold gets tuned in one place and not the other.
    #
    # How near an activity or meal has to be to an accommodation to be shown *inside* its card
    # rather than as an unrelated entry. 150 m is "the same building or its car park".
    suggestion_group_radius_m: float = 150.0
    # How far a pin has to move before the Distance Matrix is asked again. Below this the move
    # is jitter, and re-querying would spend the API budget on a pin that did not really move.
    suggestion_move_epsilon_m: float = 25.0
    # The radius of the region seeded from a decided poll option (PL-14). A first sketch of
    # "somewhere around here", meant to be redrawn — not a claim about where the trip will be.
    region_seed_radius_m: float = 15_000.0

    # --- Distances ---------------------------------------------------------
    # Distance Matrix's documented per-request caps, named here rather than left as literals in
    # the service (`distances/tasks.md` Phase 2) so that a change at Google's end is one edit
    # in one place instead of a hunt through query-building code.
    distance_max_origins: int = 25
    distance_max_destinations: int = 25
    distance_max_elements: int = 100
    # How many times a transient failure is retried before the row settles at `failed` and is
    # left alone until an organiser's explicit force-recompute. Without a cap, one bad
    # afternoon at the API becomes an unbounded retry storm against a paid endpoint.
    distance_max_attempts: int = 3
    # How long a claimed-but-unanswered pair belongs to the task that claimed it. This is the
    # `pending` guard `design.md` asks for: within the lease a second overlapping task finds the
    # pair already owned and makes no call, which is the realistic way this feature would leak
    # budget. Past it the claim is treated as abandoned — a process that died mid-batch must not
    # strand a pair as permanently un-recomputable.
    distance_claim_lease_seconds: float = 60.0

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
