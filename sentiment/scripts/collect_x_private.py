#!/usr/bin/env python3
"""Authenticated home-timeline collector (Section 6, Option B / Section 3.2).

Runs ONLY inside GitHub Actions (or another private backend) - never on
GitHub Pages, per Section 6's explicit warning. Writes raw text to the
private layer only; the redaction step (lib/redact.py) is what's allowed
to touch it before anything reaches the public payload.

This script is opt-in: it does nothing unless SENTIMENT_X_MODE is
'private_home' or 'hybrid' AND all five OAuth secrets are present. Missing
secrets = silent no-op for this collector, not a failure, since public-search
mode should keep working without it (Section 6, Section 9).

Not exercised against the live API in this sandbox - same caveat as
collect_x_public.py.
"""
import hmac
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "private", "sentiment", "x_private_raw.jsonl")
TIMELINE_URL = "https://api.x.com/2/users/{user_id}/timelines/reverse_chronological"

REQUIRED_SECRETS = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "X_USER_ID"]


def oauth1_header(method: str, url: str, params: dict, keys: dict) -> str:
    """Minimal OAuth 1.0a User Context signing (no external dependency).

    X's timeline endpoint is documented for both OAuth1 user-context and
    OAuth2 user-context; OAuth1 is used here since it doesn't require an
    interactive browser consent step, which fits an unattended Actions run.
    """
    oauth_params = {
        "oauth_consumer_key": keys["api_key"],
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": keys["access_token"],
        "oauth_version": "1.0",
    }
    all_params = {**params, **oauth_params}
    base_str = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(all_params.items())
    )
    base_string = f"{method.upper()}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(base_str, safe='')}"
    signing_key = f"{urllib.parse.quote(keys['api_secret'], safe='')}&{urllib.parse.quote(keys['access_token_secret'], safe='')}"
    signature = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    import base64
    oauth_params["oauth_signature"] = base64.b64encode(signature).decode()

    header = "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"' for k, v in oauth_params.items()
    )
    return header


def main():
    mode = os.environ.get("SENTIMENT_X_MODE", "public_search")
    if mode not in ("private_home", "hybrid"):
        print("Private-account mode not enabled (SENTIMENT_X_MODE); skipping.")
        return

    keys = {
        "api_key": os.environ.get("X_API_KEY"),
        "api_secret": os.environ.get("X_API_SECRET"),
        "access_token": os.environ.get("X_ACCESS_TOKEN"),
        "access_token_secret": os.environ.get("X_ACCESS_TOKEN_SECRET"),
    }
    user_id = os.environ.get("X_USER_ID")

    missing = [name for name, val in zip(REQUIRED_SECRETS, [keys["api_key"], keys["api_secret"],
               keys["access_token"], keys["access_token_secret"], user_id]) if not val]
    if missing:
        print(f"Private-account mode requested but missing secrets: {missing}. Skipping (no-op).", file=sys.stderr)
        return

    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else None
    params = {"max_results": "100", "tweet.fields": "created_at,author_id"}
    url = TIMELINE_URL.format(user_id=user_id)
    if since:
        params["start_time"] = since

    query_string = urllib.parse.urlencode(sorted(params.items()))
    full_url = f"{url}?{query_string}"
    auth_header = oauth1_header("GET", url, params, keys)

    req = urllib.request.Request(full_url, headers={"Authorization": auth_header})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"Private timeline collection failed: {exc}", file=sys.stderr)
        sys.exit(1)  # do not advance cursor on failure (Section 9)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    count = 0
    with open(OUT_PATH, "a") as out:
        for tweet in data.get("data", []):
            record = {
                "source_type": "x",
                "raw_text": tweet.get("text", ""),
                "author_ref": tweet.get("author_id", ""),
                "timestamp": tweet.get("created_at"),
                "platform_id": tweet.get("id"),
                "origin": "authenticated_home_timeline",
            }
            out.write(json.dumps(record) + "\n")
            count += 1

    print(f"Collected {count} private-timeline items (local-only, will be redacted before aggregation).")


if __name__ == "__main__":
    main()
