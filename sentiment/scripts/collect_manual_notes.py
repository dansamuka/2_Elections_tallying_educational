#!/usr/bin/env python3
"""Ingest manually-entered verified incident notes (Section 1.4).

Reads config/manual_notes.json (a human-maintained file, edited by whoever
you designate as a trusted observer) and appends new entries to the private
layer as source_type "manual". These get NO alert-suppression treatment -
a manual note is already a human judgment call, so it can go straight to
`reported` or `corroborated` status without needing the automated
corroboration count from pipeline_alerts.py. Promotion to
`officially_confirmed` still requires an explicit status field set by a
human in this same file - never inferred.
"""
import json
import os

MANUAL_NOTES_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "manual_notes.json")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "private", "sentiment", "manual_raw.jsonl")
SEEN_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "private", "sentiment", "manual_seen.json")


def main():
    if not os.path.exists(MANUAL_NOTES_PATH):
        print("No config/manual_notes.json present - manual notes disabled this run.")
        return

    with open(MANUAL_NOTES_PATH) as f:
        notes = json.load(f).get("notes", [])

    seen = set()
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH) as f:
            seen = set(json.load(f))

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    new_count = 0
    with open(OUT_PATH, "a") as out:
        for note in notes:
            note_id = note.get("id")
            if not note_id or note_id in seen:
                continue
            record = {
                "source_type": "manual",
                "raw_text": note.get("text", ""),
                "timestamp": note.get("timestamp"),
                "topic_hint": note.get("topic"),
                "status_hint": note.get("status", "reported"),  # human already made this call
                "author_ref": f"manual:{note_id}",
            }
            out.write(json.dumps(record) + "\n")
            seen.add(note_id)
            new_count += 1

    with open(SEEN_PATH, "w") as f:
        json.dump(sorted(seen), f)

    print(f"Ingested {new_count} new manual notes.")


if __name__ == "__main__":
    main()
