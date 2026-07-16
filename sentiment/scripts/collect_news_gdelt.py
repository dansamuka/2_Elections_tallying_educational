#!/usr/bin/env python3
"""GDELT DOC 2 API news collector (Section 1.3, Section 7's "news" source_type).

Writes to data/private/sentiment/news_raw.jsonl. GDELT's DOC API is public
and unauthenticated, so this collector has no secret dependency - it should
be the most reliable source to fall back on if X collection is degraded.

Not exercised against the live endpoint in this sandbox (the GDELT domain
isn't on the allowed network list here); written against the documented
DOC 2 API contract.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "sentiment_config.json")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "private", "sentiment", "news_raw.jsonl")
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", required=True, help="ISO-8601 cursor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    query = cfg["gdelt"]["query"]
    max_records = cfg["gdelt"].get("max_records", 75)

    # GDELT wants YYYYMMDDHHMMSS, not ISO-8601 - convert defensively.
    since_compact = args.since.replace("-", "").replace(":", "").replace("T", "").split(".")[0].split("+")[0]
    if len(since_compact) < 14:
        since_compact = (since_compact + "00000000000000")[:14]

    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(max_records),
        "startdatetime": since_compact,
    }
    url = GDELT_URL + "?" + urllib.parse.urlencode(params)

    if args.dry_run:
        print("URL:", url)
        return

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ol-kalou-observatory/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"GDELT collection failed: {exc}", file=sys.stderr)
        sys.exit(1)  # do not advance cursor on failure (Section 9)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    count = 0
    with open(OUT_PATH, "a") as out:
        for article in data.get("articles", []):
            record = {
                "source_type": "news",
                "raw_text": (article.get("title") or "") + ". " + (article.get("seendate") or ""),
                "headline": article.get("title", ""),
                "outlet": article.get("domain", ""),
                "url": article.get("url", ""),
                "timestamp": article.get("seendate", ""),
            }
            out.write(json.dumps(record) + "\n")
            count += 1

    print(f"Collected {count} news items.")


if __name__ == "__main__":
    main()
