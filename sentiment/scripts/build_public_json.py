#!/usr/bin/env python3
"""Orchestrates Section 5's pipeline end to end and writes
data/public/sentiment/latest.json against the Section 8 contract.

    raw jsonl (private) -> normalize -> dedupe -> redact -> classify
    -> sentiment -> confidence + alerts -> aggregate -> public JSON

Run with --demo to generate a payload from synthetic demo data instead of
the private raw files, for dashboard development and the acceptance test
in Section 11, test 8 ("dashboard loads in demo mode when the live JSON is
unavailable").
"""
import argparse
import glob
import json
import os
import secrets
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import pipeline_normalize
import pipeline_dedupe
import pipeline_redact
import pipeline_classify
import pipeline_sentiment
import pipeline_confidence
import pipeline_alerts
from lib.candidate_alias import build_alias_index
from lib.redact import to_public_safe, assert_no_secrets_leaked

# MODULE_ROOT = this "sentiment/" folder (holds config/, scripts/, tests/).
# REPO_ROOT = one level up - the actual repo root, where the EXISTING
# data/public/ folder lives (data/public/elections, data/public/live.json,
# etc). pages.yml's build step only copies repo-root data/public/. into the
# deployed site, so the alert/sentiment JSON has to land there too, not in a
# module-local data/public/ that the real deploy pipeline never sees.
MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(MODULE_ROOT)
CONFIG_PATH = os.path.join(MODULE_ROOT, "config", "sentiment_config.json")
OVERRIDES_PATH = os.path.join(MODULE_ROOT, "config", "incident_overrides.json")
PRIVATE_DIR = os.path.join(MODULE_ROOT, "data", "private", "sentiment")  # self-contained, never published
PUBLIC_PATH = os.path.join(REPO_ROOT, "data", "public", "sentiment", "latest.json")

REQUIRED_NOTICE = (
    "This dashboard measures online discussion, not voter intention. X users and "
    "news coverage are not representative of Ol Kalou voters. Sentiment models can "
    "misread sarcasm, Kikuyu, Kiswahili, Sheng, names, quotations, and political "
    "slogans. Official election information and results come from IEBC."
)

ALERT_DISCLAIMER = (
    "Alerts reflect volume and repetition in public conversation, not confirmed "
    "events. Only entries marked 'officially confirmed' have been verified by an authority."
)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def load_raw_items() -> list:
    items = []
    for path in glob.glob(os.path.join(PRIVATE_DIR, "*_raw.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
    return items


def make_demo_items() -> list:
    """Small synthetic dataset covering every language/topic/status path,
    used for dashboard development and CI smoke tests without needing live
    X/GDELT access."""
    now = datetime.now(timezone.utc).isoformat()
    demo = [
        # Nyagah mentions - enough volume/diversity to clear the 5-item candidate floor
        {"source_type": "x", "raw_text": "Nyagah's rally in Ol Kalou today was poa, good turnout and peaceful.", "author_ref": "u1", "timestamp": now},
        {"source_type": "x", "raw_text": "Samuel Nyagah team says momentum is building in Ol Kalou ahead of the vote.", "author_ref": "u2", "timestamp": now},
        {"source_type": "x", "raw_text": "Not everyone is happy, some say Nyagah's promises are hovyo and won't be kept.", "author_ref": "u3", "timestamp": now},
        {"source_type": "news", "raw_text": "Nyagah closes campaign with a rally in Ol Kalou town, UDA candidate confident.", "headline": "Nyagah closes campaign in Ol Kalou", "outlet": "example-news.co.ke", "timestamp": now},
        {"source_type": "x", "raw_text": "Muchina Nyagah supporters singing in the streets of Ol Kalou this morning.", "author_ref": "u4", "timestamp": now},
        {"source_type": "manual", "raw_text": "Observer note: Nyagah rally passed peacefully, large crowd, no incidents.", "author_ref": "manual:obs-2", "timestamp": now, "status_hint": "reported"},

        # Turnout / admin chatter
        {"source_type": "x", "raw_text": "Sammy Ngotho supporters say the queue at the polling station is huge, IEBC turnout looks strong.", "author_ref": "u5", "timestamp": now},
        {"source_type": "news", "raw_text": "IEBC reports smooth opening of polling stations across Ol Kalou constituency.", "headline": "IEBC reports smooth opening", "outlet": "example-news.co.ke", "timestamp": now},

        # Security cluster - deliberately over the stricter security alert threshold
        # (min_items=10, min_sources=3, min_confidence=0.75) to exercise the alert path end to end.
        {"source_type": "x", "raw_text": "Heard a scuffle and clash broke out near a polling station in Ol Kalou, police called.", "author_ref": "u6", "timestamp": now},
        {"source_type": "x", "raw_text": "Another account: confirmed clash and teargas near Ol Kalou polling station, very tense unrest.", "author_ref": "u7", "timestamp": now},
        {"source_type": "x", "raw_text": "Third post: violence and intimidation reported at Ol Kalou polling station, security officers on site.", "author_ref": "u8", "timestamp": now},
        {"source_type": "x", "raw_text": "Fourth account describing the same clash and teargas near the Ol Kalou polling station.", "author_ref": "u9", "timestamp": now},
        {"source_type": "x", "raw_text": "Police and security officers moved in after violence and a scuffle broke out in Ol Kalou.", "author_ref": "u10", "timestamp": now},
        {"source_type": "news", "raw_text": "Security officers deployed after clash and unrest reported near an Ol Kalou polling station.", "headline": "Security deployed after clash reported", "outlet": "example-news.co.ke", "timestamp": now},
        {"source_type": "x", "raw_text": "Fifth person also describing violence, teargas, and police intimidation near the station.", "author_ref": "u11", "timestamp": now},
        {"source_type": "x", "raw_text": "Sixth witness account of the clash, teargas and security officers responding in Ol Kalou.", "author_ref": "u12", "timestamp": now},
        {"source_type": "x", "raw_text": "Seventh post repeating claims of unrest, violence, and a scuffle at the polling station.", "author_ref": "u13", "timestamp": now},
        {"source_type": "x", "raw_text": "Eighth account: intimidation and clash near the Ol Kalou polling station, police on scene.", "author_ref": "u14", "timestamp": now},

        {"source_type": "x", "raw_text": "This is mbaya, hongo claims circulating about Kigwa camp, unverified so far.", "author_ref": "u15", "timestamp": now},
        {"source_type": "manual", "raw_text": "Observer note: minor delay opening one station, resolved within 30 minutes.", "author_ref": "manual:obs-1", "timestamp": now, "topic_hint": "admin", "status_hint": "corroborated"},
    ]
    return demo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Build from synthetic demo data instead of private raw files")
    parser.add_argument("--mode", default="live", choices=["live", "demo", "partial"])
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH, {})
    alias_index = build_alias_index(cfg["candidates"])
    overrides = load_json(OVERRIDES_PATH, {"overrides": []}).get("overrides", [])
    previous_public = load_json(PUBLIC_PATH, {})
    previous_alerts = {a["id"]: a for a in previous_public.get("alerts", [])}
    previous_cursor = previous_public.get("meta", {}).get("collection_cursor")

    raw_items = make_demo_items() if args.demo else load_raw_items()
    if not raw_items and not args.demo:
        print("No new raw items this run - publishing an unchanged payload with a refreshed generated_at.")

    run_salt = secrets.token_hex(8)  # per-run only; see lib/text_utils.stable_author_bucket docstring

    items = pipeline_normalize.run(raw_items)
    items = pipeline_dedupe.run(items, run_salt)
    items = pipeline_redact.run(items)
    items = pipeline_classify.run(items, cfg, alias_index)
    items = pipeline_sentiment.run(items, cfg)

    # ---- aggregate: candidates ----
    min_cell = cfg["display_thresholds"]["min_independent_items_for_cell"]
    candidates_out = []
    for cand in cfg["candidates"]:
        cand_items = [i for i in items if cand["id"] in i.get("candidate_ids", [])]
        conf = pipeline_confidence.compute(cand_items)
        if conf["item_count"] < min_cell:
            candidates_out.append({
                "id": cand["id"], "name": cand["name"], "party": cand["party"],
                "suppressed": True,
                "reason": f"Fewer than {min_cell} independent items this window.",
            })
            continue

        pos = sum(1 for i in cand_items if i.get("sentiment_label") == "positive")
        neg = sum(1 for i in cand_items if i.get("sentiment_label") == "negative")
        neu = sum(1 for i in cand_items if i.get("sentiment_label") == "neutral")
        scored = pos + neg + neu
        net_index = round(((pos - neg) / scored) * 100, 1) if scored else None

        candidates_out.append({
            "id": cand["id"], "name": cand["name"], "party": cand["party"],
            "suppressed": False,
            "mention_count": conf["item_count"],
            "positive": pos, "neutral": neu, "negative": neg,
            "unscored": conf["item_count"] - scored,
            "net_sentiment_index": net_index,
            "source_mix": {"x": conf["x_count"], "news": conf["news_count"], "manual": conf["manual_count"]},
            "confidence": conf["label"],
        })

    total_relevant = len(items)
    mentioned_total = sum(c.get("mention_count", 0) for c in candidates_out if not c["suppressed"])

    # ---- aggregate: topics (Section 4.4, full set - not just alert-eligible) ----
    topics_out = []
    for topic in cfg["topic_keywords"].keys():
        topic_items = [i for i in items if i.get("topic") == topic]
        conf = pipeline_confidence.compute(topic_items)
        if conf["item_count"] < min_cell:
            topics_out.append({"topic": topic, "suppressed": True})
            continue
        pos = sum(1 for i in topic_items if i.get("sentiment_label") == "positive")
        neg = sum(1 for i in topic_items if i.get("sentiment_label") == "negative")
        topics_out.append({
            "topic": topic, "suppressed": False,
            "item_count": conf["item_count"],
            "positive": pos, "negative": neg,
            "confidence": conf["label"],
        })

    # ---- articles (Section 4.5 - title/source/timestamp/link only) ----
    articles_out = [
        {
            "headline": i.get("headline"),
            "outlet": i.get("outlet"),
            "timestamp": i.get("timestamp"),
            "url": i.get("url"),
            "sentiment_label": i.get("sentiment_label"),
        }
        for i in items if i.get("source_type") == "news"
    ]

    # ---- quality panel (Section 4.6) ----
    total_raw = sum(i.get("frequency", 1) for i in items)
    duplicate_count = total_raw - len(items)
    unsupported_lang_count = sum(1 for i in items if i.get("language") == "unknown")
    x_items = [i for i in items if i.get("source_type") == "x"]
    outlet_counts = {}
    for i in items:
        if i.get("source_type") == "news" and i.get("outlet"):
            outlet_counts[i["outlet"]] = outlet_counts.get(i["outlet"], 0) + 1
    source_concentration = max(outlet_counts.values()) / len(items) if outlet_counts and items else 0.0

    anomaly_flags = []
    prev_summary = previous_public.get("summary", {})
    prev_total = prev_summary.get("total_relevant_items", 0)
    if prev_total and total_relevant > prev_total * 3:
        anomaly_flags.append("sudden_volume_increase")

    quality = {
        "exact_and_near_duplicate_rate": round(duplicate_count / total_raw, 3) if total_raw else 0.0,
        "repost_share": round(duplicate_count / total_raw, 3) if total_raw else 0.0,
        "source_concentration": round(source_concentration, 3),
        "unsupported_language_share": round(unsupported_lang_count / len(items), 3) if items else 0.0,
        "anomaly_flags": anomaly_flags,
        "sampling_warnings": [] if raw_items else ["No new items collected this run - check collector logs and API credentials."],
    }

    # ---- alerts (Addendum) ----
    alerts_out = pipeline_alerts.generate(items, cfg, previous_alerts, overrides)

    # ---- final payload ----
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "meta": {
            "election_id": cfg["election_id"],
            "generated_at": generated_at,
            "collection_cursor": generated_at,  # next run starts from here (Section 9)
            "mode": "demo" if args.demo else args.mode,
            "disclaimer": REQUIRED_NOTICE,
            "alert_disclaimer": ALERT_DISCLAIMER,
        },
        "summary": {
            "total_relevant_items": total_relevant,
            "x_items": len(x_items),
            "news_items": len(articles_out),
            "unique_source_estimate": len({a for i in items for a in i.get("author_buckets", set())}),
            "duplicated_share": quality["repost_share"],
            "overall_balance": {
                "positive": sum(1 for i in items if i.get("sentiment_label") == "positive"),
                "neutral": sum(1 for i in items if i.get("sentiment_label") == "neutral"),
                "negative": sum(1 for i in items if i.get("sentiment_label") == "negative"),
                "unscored": sum(1 for i in items if i.get("sentiment_label") == "unscored"),
            },
        },
        "timeline": [],  # populated by successive runs appending a point; left for the Actions workflow to accumulate
        "candidates": candidates_out,
        "topics": topics_out,
        "sources": [{"outlet": k, "count": v} for k, v in sorted(outlet_counts.items(), key=lambda kv: -kv[1])],
        "articles": articles_out,
        "quality": quality,
        "alerts": alerts_out,
    }

    payload_str = json.dumps(payload)
    secret_values = [os.environ.get(k) for k in
                      ("X_BEARER_TOKEN", "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")]
    assert_no_secrets_leaked(payload_str, secret_values)  # Section 11, test 1

    os.makedirs(os.path.dirname(PUBLIC_PATH), exist_ok=True)
    with open(PUBLIC_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote {PUBLIC_PATH} ({total_relevant} items, {len(alerts_out)} active alerts).")


if __name__ == "__main__":
    main()
