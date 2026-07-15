from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_sources(doc: dict[str, Any]) -> dict[str, str]:
    forms = doc.get("forms", {})
    return {
        str(item.get("source_url") or key): str(item.get("sha256") or "")
        for key, item in forms.items()
    }


def _stream_sources(doc: dict[str, Any]) -> set[str]:
    return {
        str(row.get("portal_source_url"))
        for row in doc.get("streams", [])
        if row.get("portal_source_url")
    }




def _stream_identity_by_source(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    keys = (
        "stream_key",
        "polling_station_code",
        "polling_centre_code",
        "station_name",
        "polling_centre_name",
        "stream_no",
        "ward_code",
        "ward_name",
        "registered",
    )
    return {
        str(row.get("portal_source_url")): {key: row.get(key) for key in keys}
        for row in doc.get("streams", [])
        if row.get("portal_source_url")
    }

def _prefills(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("stream_key")): dict((row.get("ocr") or {}).get("prefill") or {})
        for row in payload.get("streams", [])
        if row.get("stream_key")
    }


def _candidate_snapshot(payload: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ("id", "ballot_no", "name", "party", "abbr", "votes", "share")
    return [{key: row.get(key) for key in keys} for row in payload.get("candidates", [])]


def compare(
    before_payload: dict[str, Any],
    after_payload: dict[str, Any],
    before_streams: dict[str, Any],
    after_streams: dict[str, Any],
    before_manifest: dict[str, Any],
    after_manifest: dict[str, Any],
    *,
    allow_hierarchy_remap: bool = False,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []

    before_id = before_payload.get("election_id")
    after_id = after_payload.get("election_id")
    if before_id != after_id:
        errors.append(f"election_id changed: {before_id!r} -> {after_id!r}")

    immutable_sections = {
        "official_declaration": (before_payload.get("official_declaration"), after_payload.get("official_declaration")),
        "totals": (before_payload.get("totals"), after_payload.get("totals")),
        "candidate results": (_candidate_snapshot(before_payload), _candidate_snapshot(after_payload)),
    }
    for name, (before_value, after_value) in immutable_sections.items():
        if before_value != after_value:
            errors.append(f"OCR-only rebuild changed {name}")

    before_archive = before_payload.get("archive", {})
    after_archive = after_payload.get("archive", {})
    if int(after_archive.get("forms_archived") or 0) != int(before_archive.get("forms_archived") or 0):
        errors.append("forms_archived changed during OCR-only rebuild")

    before_coverage = before_payload.get("coverage", {})
    after_coverage = after_payload.get("coverage", {})
    if int(after_coverage.get("streams_total") or 0) != int(before_coverage.get("streams_total") or 0):
        errors.append("streams_total changed")
    if int(after_coverage.get("stream_rows_loaded") or 0) < int(before_coverage.get("stream_rows_loaded") or 0):
        errors.append("stream_rows_loaded decreased")

    before_sources = _manifest_sources(before_manifest)
    after_sources = _manifest_sources(after_manifest)
    if before_sources != after_sources:
        removed = sorted(set(before_sources) - set(after_sources))
        added = sorted(set(after_sources) - set(before_sources))
        changed = sorted(
            key for key in set(before_sources) & set(after_sources)
            if before_sources[key] != after_sources[key]
        )
        if removed:
            errors.append(f"source-form assignments were removed: {len(removed)}")
        if added:
            errors.append(f"source-form assignments were added during OCR-only rebuild: {len(added)}")
        if changed:
            errors.append(f"source PDF hashes changed during OCR-only rebuild: {len(changed)}")

    before_rows = list(before_streams.get("streams", []))
    after_rows = list(after_streams.get("streams", []))
    if len(after_rows) != len(before_rows):
        errors.append(f"stream-register row count changed: {len(before_rows)} -> {len(after_rows)}")

    before_portal_sources = _stream_sources(before_streams)
    after_portal_sources = _stream_sources(after_streams)
    if before_portal_sources and before_portal_sources != after_portal_sources:
        errors.append("portal_source_url coverage changed in the stream register")

    before_identity = _stream_identity_by_source(before_streams)
    after_identity = _stream_identity_by_source(after_streams)
    hierarchy_changes = [
        source
        for source in sorted(set(before_identity) & set(after_identity))
        if before_identity[source] != after_identity[source]
    ]
    registered_changes = [
        source
        for source in hierarchy_changes
        if before_identity[source].get("registered") != after_identity[source].get("registered")
    ]
    if registered_changes:
        errors.append(f"registered-voter reference values changed: {len(registered_changes)}")
    structural_changes = [source for source in hierarchy_changes if source not in registered_changes]
    if structural_changes and not allow_hierarchy_remap:
        errors.append(
            f"stream identity/hierarchy changed for {len(structural_changes)} source assignments; "
            "rerun only with explicit hierarchy-remap approval"
        )
    elif structural_changes:
        warnings.append(
            f"explicitly approved hierarchy remap changed {len(structural_changes)} source assignments"
        )

    before_pdfs = sum(1 for row in before_payload.get("streams", []) if row.get("form_url"))
    after_pdfs = sum(1 for row in after_payload.get("streams", []) if row.get("form_url"))
    if after_pdfs < before_pdfs:
        errors.append(f"stream PDF links decreased: {before_pdfs} -> {after_pdfs}")

    before_ocr = before_archive.get("ocr", {}) or {}
    after_ocr = after_archive.get("ocr", {}) or {}
    if int(after_ocr.get("pages_processed") or 0) < int(before_ocr.get("pages_processed") or 0):
        errors.append("OCR pages_processed decreased")
    if int(after_ocr.get("documents_total") or 0) < int(before_ocr.get("documents_total") or 0):
        errors.append("OCR documents_total decreased")

    before_prefills = _prefills(before_payload)
    after_prefills = _prefills(after_payload)
    common = set(before_prefills) & set(after_prefills)
    changed_prefills = sum(before_prefills[key] != after_prefills[key] for key in common)
    newly_filled = 0
    newly_blank = 0
    for key in common:
        before_values = before_prefills[key]
        after_values = after_prefills[key]
        before_count = sum(value is not None for value in before_values.values())
        after_count = sum(value is not None for value in after_values.values())
        if after_count > before_count:
            newly_filled += 1
        elif after_count < before_count:
            newly_blank += 1
    if newly_blank:
        warnings.append(f"{newly_blank} stream prefills have fewer populated fields")

    metrics = {
        "election_id": after_id,
        "safe": not errors,
        "forms_archived_before": before_archive.get("forms_archived"),
        "forms_archived_after": after_archive.get("forms_archived"),
        "streams_before": len(before_rows),
        "streams_after": len(after_rows),
        "pdf_links_before": before_pdfs,
        "pdf_links_after": after_pdfs,
        "ocr_pages_before": before_ocr.get("pages_processed"),
        "ocr_pages_after": after_ocr.get("pages_processed"),
        "review_rows_before": before_ocr.get("review_rows"),
        "review_rows_after": after_ocr.get("review_rows"),
        "prefills_compared": len(common),
        "prefills_changed": changed_prefills,
        "streams_newly_filled": newly_filled,
        "streams_newly_blank": newly_blank,
        "hierarchy_changes": len(structural_changes),
        "hierarchy_remap_allowed": allow_hierarchy_remap,
        "registered_reference_changes": len(registered_changes),
        "cloud_crop_ocr": after_ocr.get("cloud_crop_ocr"),
        "errors": errors,
        "warnings": warnings,
    }
    return errors, warnings, metrics


def _markdown(metrics: dict[str, Any]) -> str:
    status = "PASS" if metrics["safe"] else "FAIL"
    lines = [
        "# OCR rebuild safety report",
        "",
        f"**Status:** {status}",
        f"**Election:** `{metrics.get('election_id')}`",
        "",
        "| Check | Before | After |",
        "|---|---:|---:|",
        f"| Forms archived | {metrics.get('forms_archived_before')} | {metrics.get('forms_archived_after')} |",
        f"| Stream-register rows | {metrics.get('streams_before')} | {metrics.get('streams_after')} |",
        f"| Stream PDF links | {metrics.get('pdf_links_before')} | {metrics.get('pdf_links_after')} |",
        f"| OCR pages processed | {metrics.get('ocr_pages_before')} | {metrics.get('ocr_pages_after')} |",
        f"| OCR review rows | {metrics.get('review_rows_before')} | {metrics.get('review_rows_after')} |",
        "",
        f"Prefills changed: **{metrics.get('prefills_changed')}** of {metrics.get('prefills_compared')}; "
        f"streams newly filled: **{metrics.get('streams_newly_filled')}**; "
        f"streams newly blank: **{metrics.get('streams_newly_blank')}**.",
        f"Hierarchy changes: **{metrics.get('hierarchy_changes')}**; "
        f"explicitly allowed: **{metrics.get('hierarchy_remap_allowed')}**; "
        f"registered-reference changes: **{metrics.get('registered_reference_changes')}**.",
        "",
        "## Cloud crop OCR",
        "",
        "```json",
        json.dumps(metrics.get("cloud_crop_ocr"), indent=2),
        "```",
    ]
    if metrics["errors"]:
        lines += ["", "## Blocking errors", ""] + [f"- {item}" for item in metrics["errors"]]
    if metrics["warnings"]:
        lines += ["", "## Warnings", ""] + [f"- {item}" for item in metrics["warnings"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-payload", type=Path, required=True)
    parser.add_argument("--after-payload", type=Path, required=True)
    parser.add_argument("--before-streams", type=Path, required=True)
    parser.add_argument("--after-streams", type=Path, required=True)
    parser.add_argument("--before-manifest", type=Path, required=True)
    parser.add_argument("--after-manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-hierarchy-remap", action="store_true")
    args = parser.parse_args()

    errors, _, metrics = compare(
        _load(args.before_payload),
        _load(args.after_payload),
        _load(args.before_streams),
        _load(args.after_streams),
        _load(args.before_manifest),
        _load(args.after_manifest),
        allow_hierarchy_remap=args.allow_hierarchy_remap,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(_markdown(metrics), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
