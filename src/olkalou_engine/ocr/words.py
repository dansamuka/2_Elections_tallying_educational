from __future__ import annotations

import re

_SMALL = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def words_to_int(text: str) -> int | None:
    normalized = re.sub(r"[^a-z ]", " ", text.lower().replace("-", " "))
    tokens = [token for token in normalized.split() if token not in {"and", "votes", "vote"}]
    if not tokens:
        return None
    total = 0
    current = 0
    seen = False
    for token in tokens:
        if token in _SMALL:
            current += _SMALL[token]
            seen = True
        elif token in _TENS:
            current += _TENS[token]
            seen = True
        elif token == "hundred":
            current = max(current, 1) * 100
            seen = True
        elif token == "thousand":
            total += max(current, 1) * 1000
            current = 0
            seen = True
        else:
            continue
    return total + current if seen else None
