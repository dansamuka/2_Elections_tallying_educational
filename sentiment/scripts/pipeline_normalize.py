"""Stage 1: normalize (Section 7.2's normalization step, architecture Section 5)."""
import uuid
from lib.text_utils import normalize_text, content_hash


def run(raw_items: list) -> list:
    """Attach normalized_text and content_hash to every raw item.

    Assigns a fresh internal item_id (uuid4) - never the platform's own post
    ID, which stays only in the private raw record and is never propagated
    into the public-safe fields (see lib/redact.py PUBLIC_ITEM_ALLOWED_FIELDS).
    """
    out = []
    for item in raw_items:
        norm = normalize_text(item.get("raw_text", ""))
        item = dict(item)
        item["item_id"] = str(uuid.uuid4())
        item["normalized_text"] = norm
        item["content_hash"] = content_hash(norm)
        out.append(item)
    return out
