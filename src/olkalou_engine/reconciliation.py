from __future__ import annotations

from pathlib import Path
from typing import Any


def reconcile(
    candidate_names: dict[str, str],
    form35a_totals: dict[str, int],
    form35b_totals: dict[str, int],
) -> dict[str, Any]:
    rows = []
    for candidate_id in candidate_names:
        a = int(form35a_totals.get(candidate_id, 0))
        b = int(form35b_totals.get(candidate_id, 0))
        rows.append(
            {
                "candidate_id": candidate_id,
                "candidate": candidate_names[candidate_id],
                "sum_35a": a,
                "form_35b": b,
                "delta": a - b,
            }
        )
    return {
        "rows": rows,
        "reconciles": all(row["delta"] == 0 for row in rows),
        "absolute_delta": sum(abs(row["delta"]) for row in rows),
    }


def render_markdown(report: dict[str, Any], output: Path) -> None:
    lines = [
        "# Ol Kalou Form 35A / Form 35B Reconciliation",
        "",
        "> UNOFFICIAL independent verification. The Returning Officer's declaration remains authoritative.",
        "",
        f"**Overall status:** {'RECONCILED' if report['reconciles'] else 'DISCREPANCY IDENTIFIED'}",
        "",
        "| Candidate | Σ verified Form 35As | Form 35B | Delta |",
        "|---|---:|---:|---:|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['candidate']} | {row['sum_35a']:,} | {row['form_35b']:,} | {row['delta']:+,} |"
        )
    lines.extend(
        [
            "",
            f"Absolute delta across candidates: **{report['absolute_delta']:,}**.",
            "",
            "Every discrepancy must be inspected against the linked immutable form versions and the public correction log.",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
