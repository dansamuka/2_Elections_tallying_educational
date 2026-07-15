from copy import deepcopy

from scripts.validate_ocr_rebuild_safety import compare


def _fixtures():
    payload = {
        "election_id": "banissa-2025",
        "official_declaration": {"winner_id": "UDA", "winner_votes": 10431},
        "totals": {"valid_votes": 11671},
        "candidates": [
            {"id": "UDA", "ballot_no": 1, "name": "A", "party": "P", "abbr": "UDA", "votes": 10431, "share": 0.89}
        ],
        "coverage": {"streams_total": 1, "stream_rows_loaded": 1},
        "archive": {"forms_archived": 1, "ocr": {"pages_processed": 1, "documents_total": 1, "review_rows": 1}},
        "streams": [
            {"stream_key": "x", "form_url": "form.pdf", "ocr": {"prefill": {"registered": 100, "votes": {"UDA": 1}}}}
        ],
    }
    streams = {"streams": [{"stream_key": "x", "portal_source_url": "source", "registered": 100}]}
    manifest = {"forms": {"source": {"source_url": "source", "sha256": "abc"}}}
    return payload, streams, manifest


def test_safe_ocr_only_change_passes():
    before, streams, manifest = _fixtures()
    after = deepcopy(before)
    after["archive"]["ocr"]["cloud_crop_ocr"] = {"usable_values": 1}
    after["streams"][0]["ocr"]["prefill"]["votes"]["UDA"] = 84
    errors, warnings, metrics = compare(before, after, streams, streams, manifest, manifest)
    assert errors == []
    assert warnings == []
    assert metrics["prefills_changed"] == 1


def test_official_result_change_is_blocked():
    before, streams, manifest = _fixtures()
    after = deepcopy(before)
    after["official_declaration"]["winner_votes"] = 999
    errors, _, _ = compare(before, after, streams, streams, manifest, manifest)
    assert any("official_declaration" in item for item in errors)


def test_pdf_hash_change_is_blocked():
    before, streams, manifest = _fixtures()
    changed_manifest = deepcopy(manifest)
    changed_manifest["forms"]["source"]["sha256"] = "different"
    errors, _, _ = compare(before, before, streams, streams, manifest, changed_manifest)
    assert any("PDF hashes changed" in item for item in errors)


def test_stream_key_change_is_blocked_without_explicit_hierarchy_approval():
    before, streams, manifest = _fixtures()
    changed_streams = deepcopy(streams)
    changed_streams["streams"][0]["stream_key"] = "new-key"
    errors, _, metrics = compare(
        before,
        before,
        streams,
        changed_streams,
        manifest,
        manifest,
    )
    assert any("hierarchy changed" in item for item in errors)
    assert metrics["hierarchy_changes"] == 1


def test_stream_key_change_can_be_reported_with_explicit_hierarchy_approval():
    before, streams, manifest = _fixtures()
    changed_streams = deepcopy(streams)
    changed_streams["streams"][0]["stream_key"] = "new-key"
    errors, warnings, metrics = compare(
        before,
        before,
        streams,
        changed_streams,
        manifest,
        manifest,
        allow_hierarchy_remap=True,
    )
    assert errors == []
    assert any("approved hierarchy remap" in item for item in warnings)
    assert metrics["hierarchy_remap_allowed"] is True


def test_registered_reference_change_is_always_blocked():
    before, streams, manifest = _fixtures()
    changed_streams = deepcopy(streams)
    changed_streams["streams"][0]["registered"] = 999
    errors, _, metrics = compare(
        before,
        before,
        streams,
        changed_streams,
        manifest,
        manifest,
        allow_hierarchy_remap=True,
    )
    assert any("registered-voter" in item for item in errors)
    assert metrics["registered_reference_changes"] == 1
