from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Iterable

from .models import (
    CheckStatus,
    Severity,
    StreamReference,
    StreamResult,
    TrustState,
    ValidationCheck,
    ValidationReport,
)


class Validator:
    def __init__(
        self,
        *,
        confidence_threshold: float = 0.95,
        rejected_rate_low: float = 0.0,
        rejected_rate_high: float = 0.05,
    ):
        self.confidence_threshold = confidence_threshold
        self.rejected_rate_low = rejected_rate_low
        self.rejected_rate_high = rejected_rate_high

    def validate(
        self,
        result: StreamResult,
        reference: StreamReference,
        *,
        prior_versions: list[StreamResult] | None = None,
    ) -> ValidationReport:
        checks: list[ValidationCheck] = []
        valid = result.valid
        cast = result.cast

        checks.append(
            self._binary(
                "V01",
                result.po_total_valid is not None and valid == result.po_total_valid,
                Severity.CRITICAL,
                f"Candidate sum ({valid}) {'=' if result.po_total_valid == valid else '≠'} PO stated valid votes ({result.po_total_valid}).",
                observed=valid,
                expected=result.po_total_valid,
                not_run=result.po_total_valid is None,
            )
        )
        expected_cast = result.total_cast_form
        checks.append(
            self._binary(
                "V02",
                expected_cast is not None and cast == expected_cast,
                Severity.CRITICAL,
                f"Valid + rejected ({cast}) {'=' if expected_cast == cast else '≠'} PO stated total cast ({expected_cast}).",
                observed=cast,
                expected=expected_cast,
                not_run=expected_cast is None,
            )
        )
        checks.append(
            self._binary(
                "V03",
                reference.registered is not None and cast <= reference.registered,
                Severity.CRITICAL,
                f"Total cast {cast}; certified registered {reference.registered}.",
                observed=cast,
                expected=reference.registered,
                not_run=reference.registered is None,
            )
        )
        turnout = cast / reference.registered if reference.registered else None
        checks.append(
            ValidationCheck(
                code="V04",
                status=CheckStatus.WARN if turnout is not None and turnout > 0.95 else CheckStatus.PASS,
                severity=Severity.WARN,
                message=(
                    f"Turnout is {turnout:.1%}; above 95% plausibility threshold."
                    if turnout is not None and turnout > 0.95
                    else f"Turnout is {turnout:.1%}." if turnout is not None else "Turnout not computed."
                ),
                observed=turnout,
                expected="<=0.95",
            )
        )
        rejected_rate = result.rejected / cast if cast else 0.0
        rejected_warn = not (self.rejected_rate_low <= rejected_rate <= self.rejected_rate_high)
        checks.append(
            ValidationCheck(
                code="V05",
                status=CheckStatus.WARN if rejected_warn else CheckStatus.PASS,
                severity=Severity.WARN,
                message=(
                    f"Rejected-ballot rate {rejected_rate:.2%} is outside calibrated band "
                    f"[{self.rejected_rate_low:.2%}, {self.rejected_rate_high:.2%}]."
                    if rejected_warn
                    else f"Rejected-ballot rate {rejected_rate:.2%} is within calibrated band."
                ),
                observed=rejected_rate,
                expected=[self.rejected_rate_low, self.rejected_rate_high],
            )
        )
        zero_candidates = [candidate_id for candidate_id, votes in result.votes.items() if votes == 0]
        checks.append(
            ValidationCheck(
                code="V06",
                status=CheckStatus.WARN if zero_candidates else CheckStatus.PASS,
                severity=Severity.WARN,
                message=(
                    f"Zero votes recorded for: {', '.join(zero_candidates)}."
                    if zero_candidates
                    else "No candidate has a zero-vote value."
                ),
                observed=zero_candidates,
            )
        )
        checks.append(
            self._binary(
                "V07",
                result.registered_form is not None
                and reference.registered is not None
                and result.registered_form == reference.registered,
                Severity.CRITICAL,
                f"Form registered {result.registered_form}; certified register {reference.registered}.",
                observed=result.registered_form,
                expected=reference.registered,
                not_run=result.registered_form is None or reference.registered is None,
            )
        )
        conflict = False
        for old in prior_versions or []:
            if old.votes != result.votes or old.rejected != result.rejected:
                conflict = True
                break
        checks.append(
            ValidationCheck(
                code="V08",
                status=CheckStatus.FAIL if conflict else CheckStatus.PASS,
                severity=Severity.CRITICAL,
                message="Amended form differs from a prior version." if conflict else "No conflicting prior version.",
            )
        )
        confidences = list(result.field_confidence.values())
        avg_conf = mean(confidences) if confidences else 0.0
        checks.append(
            ValidationCheck(
                code="V09",
                status=CheckStatus.WARN if avg_conf < self.confidence_threshold else CheckStatus.PASS,
                severity=Severity.WARN,
                message=f"Mean field confidence {avg_conf:.3f}; threshold {self.confidence_threshold:.3f}.",
                observed=avg_conf,
                expected=self.confidence_threshold,
            )
        )
        checks.append(
            ValidationCheck(
                code="V10",
                status=CheckStatus.INFO,
                severity=Severity.INFO,
                message="Ward roll-up integrity is evaluated by the publisher after each update.",
            )
        )
        checks.append(
            ValidationCheck(
                code="V11",
                status=CheckStatus.INFO,
                severity=Severity.INFO,
                message="Vote-share outlier is evaluated after at least 10 streams report in the ward.",
            )
        )
        checks.append(
            ValidationCheck(
                code="V12",
                status=CheckStatus.INFO,
                severity=Severity.INFO,
                message="Last-digit distribution is post-election only; it is not evidence of fraud.",
            )
        )

        critical_fail = any(
            check.severity == Severity.CRITICAL and check.status == CheckStatus.FAIL
            for check in checks
        )
        auto_ready = (
            not critical_fail
            and avg_conf >= self.confidence_threshold
            and result.engine_agreement
            and result.words_agreement
        )
        route = TrustState.CONFLICTED if conflict else (
            TrustState.AUTO_VERIFIED if auto_ready else TrustState.QUARANTINED
        )
        return ValidationReport(
            stream_key=result.stream_key,
            form_version=result.form_version,
            checks=checks,
            route=route,
        )

    @staticmethod
    def _binary(
        code: str,
        passed: bool,
        severity: Severity,
        message: str,
        *,
        observed=None,
        expected=None,
        not_run: bool = False,
    ) -> ValidationCheck:
        return ValidationCheck(
            code=code,
            status=CheckStatus.NOT_RUN if not_run else (CheckStatus.PASS if passed else CheckStatus.FAIL),
            severity=severity,
            message=message,
            observed=observed,
            expected=expected,
        )


def vote_share_outliers(
    rows: Iterable[tuple[str, dict[str, int]]], minimum_streams: int = 10, sigma: float = 3.0
) -> dict[str, list[str]]:
    rows = list(rows)
    if len(rows) < minimum_streams:
        return {}
    candidate_ids = sorted({candidate for _, votes in rows for candidate in votes})
    shares: dict[str, list[tuple[str, float]]] = {candidate: [] for candidate in candidate_ids}
    for stream_key, votes in rows:
        valid = sum(votes.values())
        if valid <= 0:
            continue
        for candidate in candidate_ids:
            shares[candidate].append((stream_key, votes.get(candidate, 0) / valid))
    outliers: dict[str, list[str]] = {}
    for candidate, values in shares.items():
        numeric = [value for _, value in values]
        if len(numeric) < minimum_streams:
            continue
        mu = mean(numeric)
        sd = pstdev(numeric)
        if math.isclose(sd, 0.0):
            continue
        flagged = [stream for stream, value in values if abs(value - mu) > sigma * sd]
        if flagged:
            outliers[candidate] = flagged
    return outliers
