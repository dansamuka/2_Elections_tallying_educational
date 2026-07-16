"""Small, explicit election-flavoured Kiswahili / Sheng / Kenyan-English lexicon.

This is intentionally a short, auditable list rather than a large scraped one -
Section 7.4 requires the pipeline to report low-confidence language as
`unscored` rather than force a score, and a small transparent lexicon makes
it obvious what is and isn't covered so gaps get labelled honestly instead
of silently guessed at.
"""

POSITIVE_TERMS = {
    "poa": 0.4, "safi": 0.4, "nzuri": 0.4, "vizuri": 0.3, "sawa": 0.2,
    "furaha": 0.4, "amani": 0.3, "haki": 0.3, "ushindi": 0.4, "tunamuunga": 0.3,
    "mfano": 0.2, "makini": 0.3, "kazi nzuri": 0.4, "hongera": 0.5,
}

NEGATIVE_TERMS = {
    "mbaya": -0.4, "hovyo": -0.4, "wizi": -0.5, "udanganyifu": -0.5,
    "hongo": -0.5, "vurugu": -0.5, "uongo": -0.4, "danganya": -0.4,
    "hatari": -0.3, "kero": -0.3, "chuki": -0.4, "propaganda": -0.3,
    "aibu": -0.3, "kuvuruga": -0.4,
}

NEGATION_TERMS = {"si", "hakuna", "hapana", "hamna", "sio"}

# Slogans/quotations are common in political posts and swing generic
# sentiment models; Section 7.4 asks the pipeline to be cautious with them.
# We don't try to score slogans as sentiment - we just flag their presence
# so downstream confidence calculation can dock a point.
SLOGAN_MARKERS = {"tuko pamoja", "azimio", "kazi ni kazi", "hustler", "yote yawezekana"}


def lexicon_score(tokens: list) -> tuple:
    """Score a token list (already lowercased) against the lexicon.

    Returns (score, matched_term_count). Applies simple one-token-lookback
    negation: a negation word flips the sign of the following sentiment term.
    """
    score = 0.0
    matched = 0
    for i, tok in enumerate(tokens):
        weight = POSITIVE_TERMS.get(tok) or NEGATIVE_TERMS.get(tok)
        if weight is None:
            continue
        if i > 0 and tokens[i - 1] in NEGATION_TERMS:
            weight = -weight
        score += weight
        matched += 1
    return score, matched


def contains_slogan(text_lower: str) -> bool:
    return any(marker in text_lower for marker in SLOGAN_MARKERS)


def is_kiswahili_signal(tokens: list) -> bool:
    """Rough language signal: any lexicon hit at all counts as a Kiswahili cue."""
    return any(t in POSITIVE_TERMS or t in NEGATIVE_TERMS or t in NEGATION_TERMS for t in tokens)
