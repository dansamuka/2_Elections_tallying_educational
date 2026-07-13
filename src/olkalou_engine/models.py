from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TrustState(StrEnum):
    AWAITING = "AWAITING"
    DISCOVERED = "DISCOVERED"
    ARCHIVED = "ARCHIVED"
    EXTRACTED = "EXTRACTED"
    AUTO_VERIFIED = "AUTO_VERIFIED"
    QUARANTINED = "QUARANTINED"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"
    PUBLISHED = "PUBLISHED"
    DISPUTED = "DISPUTED"
    CONFLICTED = "CONFLICTED"
    DISRUPTED = "DISRUPTED"
    POSTPONED = "POSTPONED"
    VOIDED = "VOIDED"


class VerificationType(StrEnum):
    NONE = "NONE"
    MACHINE = "MACHINE"
    HUMAN = "HUMAN"
    DISPUTED = "DISPUTED"


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    INFO = "INFO"
    NOT_RUN = "NOT_RUN"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    WARN = "WARN"
    INFO = "INFO"


class Candidate(BaseModel):
    id: str
    ballot_no: int | None = None
    name: str
    party: str
    abbr: str
    colour: str
    bloc: str


class CandidateReference(BaseModel):
    source: str
    source_url: str | None = None
    source_verified: bool = False
    ballot_order_verified: bool = False
    last_checked_at: str | None = None
    candidates: list[Candidate]
    blocs: dict[str, list[str]]
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique(self) -> "CandidateReference":
        ids = [c.id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique")
        ballot = [c.ballot_no for c in self.candidates if c.ballot_no is not None]
        if len(ballot) != len(set(ballot)):
            raise ValueError("ballot numbers must be unique")
        return self


class StreamReference(BaseModel):
    stream_key: str
    station_code: str
    station_name: str
    stream_no: int
    ward_code: str
    ward_name: str
    registered: int | None = None
    baseline_2022: dict[str, int] | None = None
    reference_status: str = "UNRESOLVED"


class StreamsReference(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    schema_name: str = Field(default="olkalou.streams.v2", alias="schema")
    constituency: dict[str, str]
    register_source: str
    register_source_url: str | None = None
    register_source_verified: bool = False
    register_total: int
    ward_summary: list[dict[str, Any]]
    streams: list[StreamReference]
    notes: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return (
            self.register_source_verified
            and len(self.streams) == 144
            and all(s.registered is not None and s.reference_status == "VERIFIED" for s in self.streams)
            and sum(int(s.registered or 0) for s in self.streams) == self.register_total
        )


class PortalForm(BaseModel):
    source_url: str
    source_label: str
    stream_key: str | None = None
    station_name: str | None = None
    stream_no: int | None = None
    form_type: str = "35A"
    etag: str | None = None
    last_modified: str | None = None


class ExtractionField(BaseModel):
    value: int | None
    confidence: float = 0.0
    engine_values: dict[str, int | None] = Field(default_factory=dict)
    words_value: int | None = None
    words_raw: str | None = None
    consensus: bool = False


class ExtractionResult(BaseModel):
    stream_key: str
    form_version: int
    fields: dict[str, ExtractionField]
    mean_confidence: float = 0.0
    engines: list[str] = Field(default_factory=list)
    extracted_at: str = Field(default_factory=utc_now_iso)
    route: str = "QUARANTINE"


class StreamResult(BaseModel):
    stream_key: str
    form_version: int
    registered_form: int | None = None
    votes: dict[str, int]
    rejected: int
    po_total_valid: int | None = None
    total_cast_form: int | None = None
    field_confidence: dict[str, float] = Field(default_factory=dict)
    engine_agreement: bool = False
    words_agreement: bool = False
    form_url: str
    source_url: str
    sha256: str

    @property
    def valid(self) -> int:
        return sum(self.votes.values())

    @property
    def cast(self) -> int:
        return self.valid + self.rejected


class ValidationCheck(BaseModel):
    code: str
    status: CheckStatus
    severity: Severity
    message: str
    observed: Any = None
    expected: Any = None


class ValidationReport(BaseModel):
    stream_key: str
    form_version: int
    checks: list[ValidationCheck]
    route: TrustState
    created_at: str = Field(default_factory=utc_now_iso)

    @property
    def has_critical_failure(self) -> bool:
        return any(c.severity == Severity.CRITICAL and c.status == CheckStatus.FAIL for c in self.checks)


class ReviewEntry(BaseModel):
    stream_key: str
    form_version: int
    reviewer_id: str
    votes: dict[str, int]
    rejected: int
    registered_form: int | None = None
    po_total_valid: int | None = None
    total_cast_form: int | None = None
    notes: str | None = None
    submitted_at: str = Field(default_factory=utc_now_iso)

    @model_validator(mode="after")
    def non_negative(self) -> "ReviewEntry":
        values = list(self.votes.values()) + [self.rejected]
        if any(v < 0 for v in values):
            raise ValueError("vote values cannot be negative")
        return self
