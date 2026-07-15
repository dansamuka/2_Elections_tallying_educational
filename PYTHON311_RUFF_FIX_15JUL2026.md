# Python 3.11 Ruff Compatibility Hotfix — 15 July 2026

## Failure addressed

The publisher completed all 121 existing tests but stopped before GitHub push because Ruff targets Python 3.11 and rejected a nested f-string expression containing a backslash in `src/olkalou_engine/historical_identity.py`.

The failing expression constructed the whitespace-tolerant polling-station-code prefix inside an f-string expression. Python 3.12 permits this syntax, but Python 3.11 does not.

## Correction

The regular-expression prefix is now built first using ordinary string concatenation:

```python
spaced_prefix = "".join(re.escape(digit) + r"\s*" for digit in prefix)
pattern = re.compile(
    rf"(?<!\d){spaced_prefix}(?P<tail>(?:\d\s*){{9}})(?!\d)",
    re.I,
)
```

This preserves the intended OCR behaviour while remaining valid under Python 3.11 grammar.

A regression test now parses the module explicitly with Python 3.11 grammar so the incompatibility cannot silently return when tests run on Python 3.12 or 3.13.

## Validation

- Ruff `0.15.21`: all checks passed.
- Full test suite: 122 tests passed.
- Python compilation: passed.
- Targeted Malava hierarchy and Python 3.11 compatibility tests: passed.
- No repository was created or changed during packaging.

## Recovery on the existing failed local checkout

Extract the minimal hotfix into the existing repository root, allow overwrite, and run:

```bat
APPLY_PY311_RUFF_HOTFIX.cmd
```

The command validates the correction and then resumes the existing `PUSH_TO_GITHUB.cmd` workflow.
