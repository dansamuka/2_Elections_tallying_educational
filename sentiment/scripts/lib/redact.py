"""Redaction helpers. Applied to every item before it leaves the private layer.

Section 3.2 / Section 8: raw post text, usernames, account IDs, access tokens
and protected-post URLs must never reach data/public/sentiment/latest.json.
This module is the single choke point that enforces that - the aggregation
step (build_public_json.py) should only ever read the fields this module
produces, never the raw item dict.
"""
import re

_HANDLE_RE = re.compile(r"@\w+")
_URL_RE = re.compile(r"https?://\S+")
_TOKEN_LIKE_RE = re.compile(r"\b[A-Za-z0-9_\-]{20,}\b")  # catches stray bearer/access tokens pasted into text


def strip_identifiers(text: str) -> str:
    """Remove handles, URLs, and token-like strings from free text.

    Used only for producing the short human-readable `summary` field on an
    alert (Section E of the addendum) - never used to "clean up" text for
    republishing, because we don't republish raw text at all.
    """
    if not text:
        return ""
    text = _HANDLE_RE.sub("[account]", text)
    text = _URL_RE.sub("[link]", text)
    text = _TOKEN_LIKE_RE.sub("[redacted]", text)
    return text.strip()


PUBLIC_ITEM_ALLOWED_FIELDS = {
    "item_id",          # internal canonical id, not the platform's post id
    "source_type",      # "x" | "news" | "manual"
    "topic",
    "candidate_ids",
    "language",
    "sentiment_label",
    "sentiment_score",
    "timestamp",
    "is_duplicate_of",
}


def to_public_safe(item: dict) -> dict:
    """Project a private item down to only the fields allowed in aggregates.

    Any field not in PUBLIC_ITEM_ALLOWED_FIELDS is dropped, not passed through -
    fail closed, not open, if a new field is added upstream without updating
    this allowlist.
    """
    return {k: item.get(k) for k in PUBLIC_ITEM_ALLOWED_FIELDS if k in item}


def assert_no_secrets_leaked(public_payload_str: str, secret_values: list) -> None:
    """Defensive check used by validation tests (Section 11, test 1).

    Raises if any configured secret value appears verbatim in generated
    public output.
    """
    for secret in secret_values:
        if secret and secret in public_payload_str:
            raise ValueError("Secret value detected in public payload - aborting publish.")
