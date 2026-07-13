#!/usr/bin/env python3
"""Applies verified provenance corrections found during the 13 Jul 2026
audit. Run once against the extracted repo root. Idempotent-ish (re-running
just re-applies the same values), but not designed to run twice blindly --
review the diff.

Corrections:
1. Register total (73,480) upgraded from an unverified PDF citation to a
   verified one: Ol Kalou Returning Officer Anthony Njiraini is on-record
   with Daily Nation stating 73,480 voters are eligible. This is now a
   genuinely verified figure -- named official, on record, independently
   reported.
2. `ward_total_verified: true` on all 5 wards was FALSE -- no per-ward
   certified document has actually been checked against these numbers, only
   the aggregate total is now verified. This was an incorrect claim in the
   source data and is corrected to false, with a clear note distinguishing
   "internally consistent" (rows sum to the verified total) from
   "externally verified per ward" (not yet true).
3. candidates.json's source_url pointed at the SAME PDF as the register
   (implausible -- a polling-station register and a candidate list are
   normally different Gazette instruments) with no distinct corroboration.
   Added real corroborating citations: seven independent Kenyan outlets
   (Nation, KBC, Standard, Kahawatungu, Kenyans.co.ke, People Daily,
   AVDelta) consistently report these 9 names/parties. This corroborates the
   candidate ROSTER; it does NOT verify ballot order, which remains
   explicitly unverified per the existing (correct) safety notes.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERIFIED_REGISTER_NOTE = (
    "Register TOTAL (73,480) is independently verified: Ol Kalou Returning "
    "Officer Anthony Njiraini is on-record stating 73,480 voters are "
    "eligible to cast ballots in the 16 July 2026 by-election (Daily "
    "Nation, 'Shared childhoods and old rivals: Personal ties shaping Ol "
    "Kalou by-election race', ~10 Jul 2026). A second Nation piece "
    "independently references 'the area's 73,000 registered voters' "
    "('Ol-Kalou by-election: Murima referendum on who's calling the "
    "shots'), consistent with 73,480 rounded. The per-ward breakdown and "
    "the 144 individual atomic stream rows below remain NOT independently "
    "verified -- only their sum (73,480) is confirmed. Do not mark "
    "ward_total_verified true until each ward figure is checked against "
    "the certified Gazette/RO register directly."
)

CANDIDATE_CORROBORATION_NOTE = (
    "Roster corroborated (not primary-document-verified) across seven "
    "independent outlets reporting consistently on these 9 names/parties: "
    "Daily Nation, KBC Digital, The Standard, Kahawatungu, Kenyans.co.ke, "
    "People Daily, AVDelta News (May-Jul 2026 campaign coverage). "
    "source_url previously pointed at the same PDF as the polling-station "
    "register, which is not a plausible source for a candidate list -- "
    "removed rather than left implying false precision. Ballot order and "
    "legal-name spelling remain unverified against the certified list; "
    "notes below on that are unchanged and still binding."
)


def fix_streams_file(path: Path, ward_key="ward_summary"):
    d = json.loads(path.read_text())
    changed = False

    if "notes" in d:
        d["notes"] = [n for n in d["notes"] if "73,480 registered voters and 144" not in n]
        d["notes"].insert(0, VERIFIED_REGISTER_NOTE)
        changed = True
    if "register_source_verified" in d:
        # The TOTAL is now verified; the source document itself still isn't
        # independently opened/confirmed by us -- keep this false, the note
        # explains the total is verified via a different, independent route.
        pass

    for w in d.get(ward_key, []):
        if w.get("ward_total_verified") is True:
            w["ward_total_verified"] = False
            changed = True

    if changed:
        path.write_text(json.dumps(d, indent=2) + "\n")
    return changed


def fix_election_json(path: Path):
    d = json.loads(path.read_text())
    changed = False
    reg = d.get("register", {})
    if reg:
        reg["notes"] = [VERIFIED_REGISTER_NOTE] + [
            n for n in reg.get("notes", []) if "73,480 registered voters and 144" not in n
        ]
        changed = True
    for w in d.get("ward_summary", []) if "ward_summary" in d else []:
        if w.get("ward_total_verified") is True:
            w["ward_total_verified"] = False
            changed = True
    if changed:
        path.write_text(json.dumps(d, indent=2) + "\n")
    return changed


def fix_candidates_file(path: Path):
    d = json.loads(path.read_text())
    d.pop("source_url", None)
    d["source"] = (
        "IEBC Gazette Notice, 5 June 2026 (clearance) -- candidate list "
        "requires final operator verification of legal names and Form 35A "
        "row order against the certified list itself"
    )
    d["roster_corroborated"] = True
    d["notes"] = [CANDIDATE_CORROBORATION_NOTE] + d.get("notes", [])
    path.write_text(json.dumps(d, indent=2) + "\n")
    return True


def main():
    targets_streams = [
        ROOT / "data/reference/streams.json",
        ROOT / "data/elections/ol-kalou-2026/streams.json",
    ]
    for p in targets_streams:
        if p.exists():
            changed = fix_streams_file(p)
            print(f"{'Updated' if changed else 'No change'}: {p.relative_to(ROOT)}")

    election_json = ROOT / "data/elections/ol-kalou-2026/election.json"
    if election_json.exists():
        changed = fix_election_json(election_json)
        print(f"{'Updated' if changed else 'No change'}: {election_json.relative_to(ROOT)}")

    candidates_json = ROOT / "data/reference/candidates.json"
    if candidates_json.exists():
        fix_candidates_file(candidates_json)
        print(f"Updated: {candidates_json.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
