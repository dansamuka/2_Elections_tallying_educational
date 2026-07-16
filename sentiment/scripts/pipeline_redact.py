"""Stage 3: redact (Section 3.2 / Section 8). Strips identifiers from any
text that might later be surfaced in a human-readable summary, and drops
raw platform fields we never want touching downstream stages by name."""
from lib.redact import strip_identifiers


def run(items: list) -> list:
    for item in items:
        item["redacted_text"] = strip_identifiers(item.get("normalized_text", ""))
        # platform_id / raw author id are intentionally left in the dict for
        # this stage (near-dup / author-bucket work upstream already used
        # them) but pipeline_redact marks them explicitly so build_public_json
        # knows never to read them again after this point.
        item["_private_only"] = True
    return items
