#!/usr/bin/env python3
"""Collect public X posts via the recent-search endpoint (Section 6, Option A).

Writes ONLY to data/private/sentiment/x_public_raw.jsonl (never public/).
Requires X_BEARER_TOKEN in the environment. Cannot be exercised against the
real API in this sandbox (api.x.com is not on the allowed network list here) -
this script is written against the documented endpoint contract and should be
smoke-tested in your own Actions run before relying on it.

Usage:
    python3 collect_x_public.py --since <ISO-8601-cursor> [--dry-run]
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "sentiment_config.json")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "private", "sentiment", "x_public_raw.jsonl")
SEARCH_URL = "https://api.x.com/2/tweets/search/recent"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def build_query(cfg: dict) -> str:
    base = cfg["x_search"]["base_query"]
    candidate_terms = []
    for c in cfg["candidates"]:
        candidate_terms.append(c["name"])
        candidate_terms.extend(c.get("aliases", []))
    # Keep the query bounded - X recent-search has a query length limit.
    # We OR in place terms + a representative slice of candidate aliases;
    # full candidate attribution happens locally in pipeline_classify.py
    # against the FULL alias list, so a trimmed query here doesn't limit
    # attribution accuracy, only initial recall.
    place = " OR ".join(f'"{p}"' for p in cfg["place_terms"])
    query = f"({base} OR {place}) -is:retweet lang:en OR lang:sw"
    spam = cfg.get("spam_terms_exclude", [])
    for term in spam:
        query += f' -"{term}"'
    return query


def fetch_page(query: str, bearer_token: str, since_iso: str, next_token: str = None) -> dict:
    params = {
        "query": query,
        "max_results": "100",
        "tweet.fields": "created_at,author_id,public_metrics,lang",
        "start_time": since_iso,
    }
    if next_token:
        params["next_token"] = next_token
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer_token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", required=True, help="ISO-8601 cursor: only fetch posts after this time")
    parser.add_argument("--max-pages", type=int, default=5, help="Conservative page cap - X API usage is credit-based (Section 6)")
    parser.add_argument("--dry-run", action="store_true", help="Build the query and print it without calling the API")
    args = parser.parse_args()

    cfg = load_config()
    query = build_query(cfg)

    if args.dry_run:
        print("QUERY:", query)
        print("Would fetch since:", args.since)
        return

    bearer_token = os.environ.get("X_BEARER_TOKEN")
    if not bearer_token:
        print("X_BEARER_TOKEN not set - skipping public X collection this run.", file=sys.stderr)
        return

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    count = 0
    next_token = None
    with open(OUT_PATH, "a") as out:
        for page in range(args.max_pages):
            try:
                data = fetch_page(query, bearer_token, args.since, next_token)
            except Exception as exc:  # noqa: BLE001 - a failed collector must not advance the cursor (Section 9)
                print(f"X public collection failed on page {page}: {exc}", file=sys.stderr)
                sys.exit(1)

            for tweet in data.get("data", []):
                record = {
                    "source_type": "x",
                    "raw_text": tweet.get("text", ""),
                    "author_ref": tweet.get("author_id", ""),  # hashed downstream, never published
                    "timestamp": tweet.get("created_at"),
                    "platform_id": tweet.get("id"),
                }
                out.write(json.dumps(record) + "\n")
                count += 1

            next_token = data.get("meta", {}).get("next_token")
            if not next_token:
                break
            time.sleep(1)  # be polite between pages

    print(f"Collected {count} public X items.")


if __name__ == "__main__":
    main()
