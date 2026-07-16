"""Private audit trail (traceability). NEVER imported by anything that writes
to data/public/ - this module's whole job is to produce a record that must
stay off the public payload and off this repo's own Actions artifacts.

Why not GitHub Actions artifacts: on a PUBLIC repository, anyone signed into
GitHub can view and download the artifacts and logs from workflow runs -
"private" only in name. Writing raw post text there would be equivalent to
publishing it, which is exactly what Section 3.2 exists to prevent. So this
module's output is designed to be pushed to a SEPARATE, genuinely private
repository instead (see .github/workflows/sentiment_refresh.yml's
"Push evidence trail" step) - opt-in, and a no-op if that repo isn't
configured, so the safe default (raw data simply isn't retained) never
regresses if someone skips setup.

Retention and access are policy, not code - see README_sentiment.md's
"Traceability & evidence trail" section for the checklist (who has access,
how long records are kept, when to purge).
"""
import json
import os


def build_audit_record(items: list, cfg: dict, generated_at: str, alerts: list) -> dict:
    """One record per pipeline run: every item that fed this run's aggregates,
    with the fields deliberately excluded from the public payload restored -
    raw text, unhashed author reference, platform id, and which alert (if any)
    it contributed to. This is the thing you pull up if an alert needs to be
    traced back to the actual posts behind it.
    """
    alert_ids_by_category = {a["category"]: a["id"] for a in alerts}

    audit_items = []
    for item in items:
        audit_items.append({
            "item_id": item.get("item_id"),
            "source_type": item.get("source_type"),
            "platform_id": item.get("platform_id"),          # real tweet/article id - private only
            "author_ref": item.get("author_ref"),             # unhashed - private only, controlled access
            "raw_text": item.get("raw_text"),                 # untouched original text - private only
            "timestamp": item.get("timestamp"),
            "topic": item.get("topic"),
            "topic_confidence": item.get("topic_confidence"),
            "candidate_ids": item.get("candidate_ids", []),
            "matched_keywords": item.get("matched_keywords", []),
            "hashtags": item.get("hashtags", []),
            "language": item.get("language"),
            "sentiment_label": item.get("sentiment_label"),
            "sentiment_score": item.get("sentiment_score"),
            "frequency": item.get("frequency", 1),
            "content_hash": item.get("content_hash"),
            "contributed_to_alert": alert_ids_by_category.get(item.get("topic")),
            "outlet": item.get("outlet"),
            "url": item.get("url"),
        })

    return {
        "election_id": cfg["election_id"],
        "run_generated_at": generated_at,
        "item_count": len(audit_items),
        "items": audit_items,
    }


def write_audit_record(record: dict, audit_dir: str) -> str:
    os.makedirs(audit_dir, exist_ok=True)
    safe_ts = record["run_generated_at"].replace(":", "-")
    path = os.path.join(audit_dir, f"{safe_ts}.json")
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    return path
