"""Stage 4: classify (Section 7.3 language, Section 4.4/topic_keywords topic,
Section 7.5 candidate attribution)."""
from lib.text_utils import token_set
from lib.lexicon_sw_ke import is_kiswahili_signal, contains_slogan
from lib.candidate_alias import find_candidate_mentions

COMMON_ENGLISH_MARKERS = {
    "the", "and", "is", "are", "was", "were", "will", "have", "has", "this",
    "that", "election", "vote", "voting", "candidate",
}


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
    """Return (best_topic, confidence 0-1). Confidence is just matched-keyword
    density against a small expected-hit cap - simple and auditable, per the
    same "small explicit lexicon over opaque model" philosophy as Section 7.4.
    """
    scores = {}
    for topic, keywords in topic_keywords.items():
        hits = sum(1 for kw in keywords if kw.lower() in text_lower)
        if hits:
            scores[topic] = min(1.0, hits / 2.0)  # 2+ keyword hits already saturates confidence
    if not scores:
        return "general", 0.0
    best_topic = max(scores, key=scores.get)
    return best_topic, scores[best_topic]


def run(items: list, cfg: dict, alias_index: dict) -> list:
    for item in items:
        text_lower = item.get("redacted_text", "")
        tokens = list(token_set(text_lower))
        item["language"] = classify_language(tokens)
        item["has_slogan"] = contains_slogan(text_lower)
        topic, topic_conf = classify_topic(text_lower, cfg["topic_keywords"])
        item["topic"] = topic
        item["topic_confidence"] = topic_conf
        item["candidate_ids"] = sorted(find_candidate_mentions(text_lower, alias_index))
    return items
