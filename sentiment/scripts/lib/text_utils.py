"""Shared normalization / hashing / similarity helpers used across the pipeline.

No external dependencies - the GitHub Actions runner should stay cheap and fast.
"""
import hashlib
import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_MENTION_RE = re.compile(r"@\w+")
_URL_RE = re.compile(r"https?://\S+")
_PUNCT_RUN_RE = re.compile(r"([!?.,])\1{1,}")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")


def normalize_text(raw: str) -> str:
    """Lowercase, strip URLs/mentions, collapse repeated punctuation and whitespace.

    This is the canonical form used for hashing and dedup - NOT what gets
    stored or displayed (we keep original text only in the private layer).
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = text.lower()
    text = _URL_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _PUNCT_RUN_RE.sub(r"\1", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def token_set(text: str) -> set:
    """Bag-of-words token set for near-duplicate comparison (order-independent)."""
    stripped = _NON_ALNUM_RE.sub(" ", text)
    return {t for t in stripped.split() if t}


def content_hash(normalized_text: str) -> str:
    """Stable hash of normalized text for exact-duplicate grouping."""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:16]


def jaccard_similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def is_near_duplicate(text_a: str, text_b: str, threshold: float = 0.82) -> bool:
    """Token-set Jaccard similarity check used for near-duplicate clustering.

    A simple, explainable method on purpose - defensible in a validation
    report without needing an ML dependency in Phase 1.
    """
    return jaccard_similarity(token_set(text_a), token_set(text_b)) >= threshold


def stable_author_bucket(author_identifier: str, salt: str) -> str:
    """One-way hash of an author identifier, salted per-run.

    Used ONLY inside the private layer to count unique sources within a single
    run. Never written to the public payload (Section 3.2 / 11.2 - no raw
    usernames or account IDs in public output). Because the salt changes
    between runs, this hash CANNOT be used to reconcile the same author
    across separate refresh windows - that's why Section 7.6 calls the
    cumulative unique-source metric an upper-bound estimate.
    """
    return hashlib.sha256(f"{salt}:{author_identifier}".encode("utf-8")).hexdigest()[:12]
