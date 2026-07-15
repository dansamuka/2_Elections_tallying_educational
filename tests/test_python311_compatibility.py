from __future__ import annotations

import ast
from pathlib import Path


def test_historical_identity_parses_with_python_311_grammar() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "olkalou_engine"
        / "historical_identity.py"
    ).read_text(encoding="utf-8")
    ast.parse(source, filename="historical_identity.py", feature_version=(3, 11))
