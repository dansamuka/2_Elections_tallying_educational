"""Stage 5: sentiment (Section 7.4).

Combines VADER (English) with the small Kiswahili/Sheng lexicon, applies
negation handling (inside the lexicon module), and produces an `unscored`
state for low-confidence language rather than forcing a number.
"""
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from lib.lexicon_sw_ke import lexicon_score
from lib.text_utils import token_set

_analyzer = SentimentIntensityAnalyzer()


def score_item(item: dict, thresholds: dict) -> dict:
    text = item.get("redacted_text", "")
    language = item.get("language")
    tokens = list(token_set(text))

    vader_score = None
    lexicon_val = None

    if language in ("english", "mixed"):
        vader_score = _analyzer.polarity_scores(text)["compound"]

    if language in ("kiswahili", "mixed"):
        raw_score, matched = lexicon_score(tokens)
        if matched > 0:
            lexicon_val = max(-1.0, min(1.0, raw_score))  # clip to VADER's [-1, 1] range

    if language == "mixed" and vader_score is not None and lexicon_val is not None:
        combined = (vader_score + lexicon_val) / 2
    elif vader_score is not None:
        combined = vader_score
    elif lexicon_val is not None:
        combined = lexicon_val
    else:
        combined = None  # unknown language, no lexicon signal at all

    if combined is None:
        item["sentiment_score"] = None
        item["sentiment_label"] = "unscored"
        return item

    # Slogans/quotations are flagged upstream (Section 7.4's "quotation and
    # headline cautions") - we still score them but the confidence stage
    # docks a point for any cell containing flagged items, rather than
    # silently overriding the score itself.
    item["sentiment_score"] = round(combined, 3)
    if combined >= thresholds["positive_min"]:
        item["sentiment_label"] = "positive"
    elif combined <= thresholds["negative_max"]:
        item["sentiment_label"] = "negative"
    else:
        item["sentiment_label"] = "neutral"
    return item


def run(items: list, cfg: dict) -> list:
    thresholds = cfg["sentiment_thresholds"]
    for item in items:
        score_item(item, thresholds)
    return items
