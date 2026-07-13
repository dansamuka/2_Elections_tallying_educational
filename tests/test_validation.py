from olkalou_engine.models import StreamReference, StreamResult, TrustState
from olkalou_engine.validation import Validator


def make_result(**updates):
    data = dict(
        stream_key="091-001-01",
        form_version=1,
        registered_form=500,
        votes={"UDA": 200, "DCP": 150, "JUBILEE": 20},
        rejected=5,
        po_total_valid=370,
        total_cast_form=375,
        field_confidence={"UDA": 0.99, "DCP": 0.99, "JUBILEE": 0.99, "registered": 0.99},
        engine_agreement=True,
        words_agreement=True,
        form_url="https://cdn/form.jpg",
        source_url="https://iebc/form",
        sha256="a" * 64,
    )
    data.update(updates)
    return StreamResult(**data)


def reference():
    return StreamReference(
        stream_key="091-001-01",
        station_code="001",
        station_name="TEST PRIMARY",
        stream_no=1,
        ward_code="0453",
        ward_name="KARAU",
        registered=500,
        reference_status="VERIFIED",
    )


def test_clean_result_routes_auto_verified():
    report = Validator().validate(make_result(), reference())
    assert report.route == TrustState.AUTO_VERIFIED
    assert not report.has_critical_failure


def test_sum_mismatch_quarantines():
    report = Validator().validate(make_result(po_total_valid=371), reference())
    assert report.route == TrustState.QUARANTINED
    assert next(c for c in report.checks if c.code == "V01").status.value == "FAIL"


def test_amended_result_conflicts():
    old = make_result()
    new = make_result(form_version=2, votes={"UDA": 201, "DCP": 149, "JUBILEE": 20})
    report = Validator().validate(new, reference(), prior_versions=[old])
    assert report.route == TrustState.CONFLICTED
