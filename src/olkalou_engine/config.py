from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    engine_root: Path = Field(default=Path("."), alias="ENGINE_ROOT")
    worker_id: str = Field(default="worker-a", alias="WORKER_ID")
    portal_index_url: str = Field(
        default="https://forms.iebc.or.ke/index.php?l=2&p=2&r=site%2Findex",
        alias="PORTAL_INDEX_URL",
    )
    portal_constituency: str = Field(default="OL KALOU", alias="PORTAL_CONSTITUENCY")
    portal_constituency_code: str = Field(default="091", alias="PORTAL_CONSTITUENCY_CODE")
    portal_county: str = Field(default="NYANDARUA", alias="PORTAL_COUNTY")
    portal_detail_url: str | None = Field(
        default="https://forms.iebc.or.ke/index.php?r=site%2Findex&id=141&ft=&p=2&es=",
        alias="PORTAL_DETAIL_URL",
    )
    portal_poll_seconds: int = Field(default=60, ge=10, alias="PORTAL_POLL_SECONDS")
    portal_user_agent: str = Field(
        default="OlKalouCivicVerifier/0.2 (+https://example.org/methodology)",
        alias="PORTAL_USER_AGENT",
    )

    allow_incomplete_reference: bool = Field(default=False, alias="ALLOW_INCOMPLETE_REFERENCE")
    auto_publish_machine_verified: bool = Field(
        default=False, alias="AUTO_PUBLISH_MACHINE_VERIFIED"
    )
    machine_confidence_threshold: float = Field(
        default=0.95, ge=0.0, le=1.0, alias="MACHINE_CONFIDENCE_THRESHOLD"
    )
    rejected_rate_low: float = Field(default=0.0, ge=0.0, le=1.0, alias="REJECTED_RATE_LOW")
    rejected_rate_high: float = Field(default=0.05, ge=0.0, le=1.0, alias="REJECTED_RATE_HIGH")

    review_host: str = Field(default="0.0.0.0", alias="REVIEW_HOST")
    review_port: int = Field(default=8080, ge=1, le=65535, alias="REVIEW_PORT")
    review_api_token: str = Field(default="change-me", alias="REVIEW_API_TOKEN")

    # Realtime election-specific sync gateway. The static site never embeds this
    # token; an authorised operator enters it into the browser session when
    # explicitly requesting a portal check.
    realtime_host: str = Field(default="0.0.0.0", alias="REALTIME_HOST")
    realtime_port: int = Field(default=8090, ge=1, le=65535, alias="REALTIME_PORT")
    realtime_api_token: str = Field(default="change-me", alias="REALTIME_API_TOKEN")
    realtime_scheduler_enabled: bool = Field(default=True, alias="REALTIME_SCHEDULER_ENABLED")
    realtime_poll_seconds: int = Field(default=30, ge=10, alias="REALTIME_POLL_SECONDS")
    realtime_archive_poll_seconds: int = Field(default=300, ge=60, alias="REALTIME_ARCHIVE_POLL_SECONDS")
    realtime_trigger_cooldown_seconds: int = Field(default=20, ge=0, alias="REALTIME_TRIGGER_COOLDOWN_SECONDS")
    realtime_live_election_id: str = Field(default="ol-kalou-2026", alias="REALTIME_LIVE_ELECTION_ID")
    realtime_elections: str = Field(default="ol-kalou-2026", alias="REALTIME_ELECTIONS")
    realtime_engine: str = Field(default="auto", alias="REALTIME_ENGINE")
    realtime_cors_origins: str = Field(
        default="http://localhost:8000,http://127.0.0.1:8000,https://dansamuka.github.io",
        alias="REALTIME_CORS_ORIGINS",
    )

    public_base_url: str = Field(default="http://localhost:8000/data/public", alias="PUBLIC_BASE_URL")
    public_output: Path = Field(default=Path("data/public/live.json"), alias="PUBLIC_OUTPUT")

    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    s3_region: str = Field(default="auto", alias="S3_REGION")
    s3_bucket: str | None = Field(default=None, alias="S3_BUCKET")
    s3_access_key_id: str | None = Field(default=None, alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = Field(default=None, alias="S3_SECRET_ACCESS_KEY")
    s3_public_base_url: str | None = Field(default=None, alias="S3_PUBLIC_BASE_URL")
    s3_prefix: str = Field(default="ol-kalou", alias="S3_PREFIX")

    alert_webhook_url: str | None = Field(default=None, alias="ALERT_WEBHOOK_URL")

    ocr_mode: str = Field(default="none", alias="OCR_MODE")
    gcv_credentials_json: Path | None = Field(default=None, alias="GCV_CREDENTIALS_JSON")
    aws_region: str = Field(default="af-south-1", alias="AWS_REGION")
    form_roi_map: Path = Field(default=Path("data/reference/form35a_roi.json"), alias="FORM_ROI_MAP")

    @property
    def realtime_election_list(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value.strip() for value in self.realtime_elections.split(",") if value.strip()))

    @property
    def realtime_cors_origin_list(self) -> list[str]:
        values = [value.strip() for value in self.realtime_cors_origins.split(",") if value.strip()]
        return values or ["http://localhost:8000"]

    @property
    def root(self) -> Path:
        return self.engine_root.resolve()

    def path(self, value: Path | str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    @property
    def candidates_path(self) -> Path:
        return self.path("data/reference/candidates.json")

    @property
    def streams_path(self) -> Path:
        return self.path("data/reference/streams.json")

    @property
    def db_path(self) -> Path:
        return self.path("data/state/engine.sqlite3")

    @property
    def raw_dir(self) -> Path:
        return self.path("data/raw")

    @property
    def manifest_path(self) -> Path:
        return self.path("data/state/manifest.json")

    @property
    def live_path(self) -> Path:
        return self.path(self.public_output)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
