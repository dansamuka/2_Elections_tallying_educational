"""Alert generation (Addendum sections B, C, E).

Design simplification worth knowing about: this Phase-1-era implementation
tracks ONE alert bucket per (election_id, category) per run, not per discrete
incident. That's enough to answer "is there an unusual, corroborated cluster
of security-topic conversation right now" - it is NOT enough to distinguish
two unrelated security incidents happening at different polling stations on
the same day. Per-incident clustering (e.g. by named place/station) is
exactly the kind of thing the addendum earmarks for a fuller Phase 4 reviewer
console; this scaffold flags the gap rather than silently pretending to solve it.

Status can only move automatically between `watch` (internal, never
published) and `reported`. `corroborated` can be reached automatically too
(see below), but `officially_confirmed` and `retracted` are ALWAYS set by a
human, either via config/manual_notes.json status_hint or
config/incident_overrides.json - never inferred by this module.
"""
ALERT_ELIGIBLE_CATEGORIES = {"admin", "security", "integrity", "misinformation", "logistics"}

STATUS_RANK = {"watch": 0, "reported": 1, "corroborated": 2, "officially_confirmed": 3, "retracted": -1}


def _thresholds_for(category: str, cfg: dict) -> dict:
    a = cfg["alert_thresholds"]
    if category in ("security", "integrity"):
        return {
            "min_items": a[f"{category}_min_items"],
            "min_sources": a[f"{category}_min_independent_sources"],
            "min_confidence": a[f"{category}_min_topic_confidence"],
        }
    return {
        "min_items": a["generic_min_items"],
        "min_sources": a["generic_min_independent_sources"],
        "min_confidence": a["default_min_topic_confidence"],
    }


def _max_status(a: str, b: str) -> str:
    return a if STATUS_RANK.get(a, 0) >= STATUS_RANK.get(b, 0) else b


def generate(items: list, cfg: dict, previous_alerts: dict, overrides: list) -> list:
    """previous_alerts: dict of alert_id -> previous alert dict (from last
    published payload), used to preserve first_seen and never silently
    lower a status the automated pipeline itself already reached.
    """
    by_category = {}
    for item in items:
        cat = item.get("topic")
        if cat not in ALERT_ELIGIBLE_CATEGORIES:
            continue
        by_category.setdefault(cat, []).append(item)

    alerts = []
    for category, cat_items in by_category.items():
        alert_id = f"{cfg['election_id']}:{category}"
        thresholds = _thresholds_for(category, cfg)

        item_count = len(cat_items)
        independent_sources = len({a for i in cat_items for a in i.get("author_buckets", set())})
        avg_conf = sum(i.get("topic_confidence", 0) for i in cat_items) / item_count if item_count else 0.0

        meets_criteria = (
            item_count >= thresholds["min_items"]
            and independent_sources >= thresholds["min_sources"]
            and avg_conf >= thresholds["min_confidence"]
        )
        status = "reported" if meets_criteria else "watch"

        # Manual notes are a human judgment call already - they can push
        # status straight to corroborated/officially_confirmed without
        # needing the volume/source thresholds above.
        manual_hints = [i.get("status_hint") for i in cat_items if i.get("source_type") == "manual" and i.get("status_hint")]
        for hint in manual_hints:
            status = _max_status(status, hint)

        prev = previous_alerts.get(alert_id)
        if prev:
            # Never let the automated pipeline silently walk a status
            # backwards - that's an override-only action.
            status = _max_status(status, prev.get("status", "watch"))
            first_seen = prev.get("first_seen")
        else:
            first_seen = cat_items[0].get("timestamp")

        if status == "watch":
            # Internal signal only - Section D says watch-level items don't
            # appear on the public dashboard.
            continue

        alerts.append({
            "id": alert_id,
            "category": category,
            "status": status,
            "first_seen": first_seen,
            "last_updated": max((i.get("timestamp") or "" for i in cat_items), default=""),
            "item_count": item_count,
            "independent_source_count": independent_sources,
            "confidence": "higher" if avg_conf >= 0.8 else ("moderate" if avg_conf >= 0.5 else "low"),
            "summary": f"{item_count} independent items across {independent_sources} sources mention {category}-related terms in the current window.",
            "override_applied": False,
        })

    # Apply config/incident_overrides.json LAST - always wins (Addendum C).
    override_by_id = {o["id"]: o for o in overrides}
    for alert in alerts:
        if alert["id"] in override_by_id:
            ov = override_by_id[alert["id"]]
            if ov.get("status"):
                alert["status"] = ov["status"]
            if ov.get("summary"):
                alert["summary"] = ov["summary"]
            alert["override_applied"] = True

    # Also surface any override for a category with NO current-window items
    # (e.g. a human manually retracting or confirming something after the
    # live conversation about it has died down).
    existing_ids = {a["id"] for a in alerts}
    for ov in overrides:
        if ov["id"] not in existing_ids and ov.get("status"):
            prev = previous_alerts.get(ov["id"], {})
            alerts.append({
                "id": ov["id"],
                "category": ov["id"].split(":")[-1],
                "status": ov["status"],
                "first_seen": prev.get("first_seen", ov.get("first_seen", "")),
                "last_updated": ov.get("last_updated", ""),
                "item_count": prev.get("item_count", 0),
                "independent_source_count": prev.get("independent_source_count", 0),
                "confidence": prev.get("confidence", "low"),
                "summary": ov.get("summary", "Status set by manual override."),
                "override_applied": True,
            })

    return alerts
