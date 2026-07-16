"""Stage 4: classify (Section 7.3 language, Section 4.4/topic_keywords topic,
Section 7.5 candidate attribution)."""
import re
from lib.text_utils import token_set
from lib.lexicon_sw_ke import is_kiswahili_signal, contains_slogan
from lib.candidate_alias import find_candidate_mentions

COMMON_ENGLISH_MARKERS = {
    "the", "and", "is", "are", "was", "were", "will", "have", "has", "this",
    "that", "election", "vote", "voting", "candidate",
}

_HASHTAG_RE = re.compile(r"#(\w{2,30})")


def classify_language(tokens: list) -> str:
    has_sw = is_kiswahili_signal(tokens)
    has_en = any(t in COMMON_ENGLISH_MARKERS for t in tokens)
    if has_sw and has_en:
        return "mixed"
    if has_sw:
        return "kiswahili"
    if has_en:
        return "english"
    return "unknown"  # honest label per Section 7.3, not forced into english/kiswahili


def classify_topic(text_lower: str, topic_keywords: dict) -> tuple:
    """Return (best_topic, confidence 0-1, matched_keywords). Confidence is just
    matched-keyword density against a small expected-hit cap - simple and
    auditable, per the same "small explicit lexicon over opaque model"
    philosophy as Section 7.4. matched_keywords covers ALL topics an item
    hit, not just the winning one - this feeds the aggregate "trending terms"
    feature (build_public_json.py), which is why it stays a bounded,
    pre-configured vocabulary rather than arbitrary free-text n-grams: every
    term shown on the dashboard traces back to something in
    config/sentiment_config.json, not to a phrase lifted from one post.
    """
    scores = {}
    all_matched = []
    for topic, keywords in topic_keywords.items():
        hits = [kw for kw in keywords if kw.lower() in text_lower]
        if hits:
            scores[topic] = min(1.0, len(hits) / 2.0)  # 2+ keyword hits already saturates confidence
            all_matched.extend(hits)
    if not scores:
        return "general", 0.0, all_matched
    best_topic = max(scores, key=scores.get)
    return best_topic, scores[best_topic], all_matched


def extract_hashtags(text: str) -> list:
    return [f"#{m.lower()}" for m in _HASHTAG_RE.findall(text)]


def run(items: list, cfg: dict, alias_index: dict) -> list:
    for item in items:
        text_lower = item.get("redacted_text", "")
        tokens = list(token_set(text_lower))
        item["language"] = classify_language(tokens)
        item["has_slogan"] = contains_slogan(text_lower)
        topic, topic_conf, matched_keywords = classify_topic(text_lower, cfg["topic_keywords"])
        item["topic"] = topic
        item["topic_confidence"] = topic_conf
        item["matched_keywords"] = matched_keywords
        item["hashtags"] = extract_hashtags(text_lower)
        item["candidate_ids"] = sorted(find_candidate_mentions(text_lower, alias_index))
    return items
