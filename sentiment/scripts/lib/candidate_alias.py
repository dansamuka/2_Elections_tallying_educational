"""Resolve free text against configured candidate aliases (Section 2 / test 3)."""
import re


def build_alias_index(candidates: list) -> dict:
    """Map each lowercased alias/name -> candidate id, longest-alias-first
    so 'Wangui Njoroge' doesn't get eaten by a shorter partial match first."""
    index = {}
    for c in candidates:
        names = [c["name"]] + c.get("aliases", [])
        for n in names:
            index[n.lower()] = c["id"]
    return index


def find_candidate_mentions(text_lower: str, alias_index: dict) -> set:
    """Return the set of candidate ids mentioned in text_lower.

    Longest-match-first avoids a short alias silently absorbing hits meant
    for a different, longer alias of the same or another candidate.
    """
    hits = set()
    for alias in sorted(alias_index.keys(), key=len, reverse=True):
        if re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
            hits.add(alias_index[alias])
    return hits
