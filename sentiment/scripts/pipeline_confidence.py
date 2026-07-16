"""Stage 6 (part of aggregation): confidence (Section 7.6).

Confidence is computed per aggregate cell (a candidate, or a topic), never
per raw item - a single post doesn't have a "confidence", a claim about
public conversation does. Labels are low/moderate/higher, and the code
deliberately has no path to a "certain" label, per Section 7.6.
"""


def compute(cell_items: list) -> dict:
    count = len(cell_items)
    if count == 0:
        return {"score": 0.0, "label": "low", "item_count": 0}

    unique_sources = len({a for item in cell_items for a in item.get("author_buckets", set())})
    x_count = sum(1 for i in cell_items if i.get("source_type") == "x")
    news_count = sum(1 for i in cell_items if i.get("source_type") == "news")
    manual_count = sum(1 for i in cell_items if i.get("source_type") == "manual")
    scored_count = sum(1 for i in cell_items if i.get("sentiment_label") != "unscored")
    slogan_count = sum(1 for i in cell_items if i.get("has_slogan"))
    total_repost_weight = sum(i.get("frequency", 1) for i in cell_items)

    volume_factor = min(1.0, count / 8.0)
    source_factor = min(1.0, unique_sources / 5.0) if unique_sources else 0.0
    duplicate_ratio = 1 - (unique_sources / total_repost_weight) if total_repost_weight else 0.0
    dup_penalty_factor = 1 - min(0.5, duplicate_ratio)
    language_factor = scored_count / count if count else 0.0
    balance_factor = 1.0 if (x_count > 0 and (news_count > 0 or manual_count > 0)) else 0.75
    slogan_penalty = max(0.0, 1 - (slogan_count / count) * 0.2) if count else 1.0

    composite = (
        0.25 * volume_factor
        + 0.20 * source_factor
        + 0.15 * dup_penalty_factor
        + 0.20 * language_factor
        + 0.10 * balance_factor
        + 0.10 * slogan_penalty
    )

    if composite < 0.35:
        label = "low"
    elif composite < 0.65:
        label = "moderate"
    else:
        label = "higher"

    return {
        "score": round(composite, 3),
        "label": label,
        "item_count": count,
        "independent_source_estimate": unique_sources,
        "x_count": x_count,
        "news_count": news_count,
        "manual_count": manual_count,
    }
