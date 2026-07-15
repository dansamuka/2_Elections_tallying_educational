from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "rebuild-ocr-only.yml"
)


def test_dependency_install_never_builds_inside_primary_checkout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pip install '.[historical-ocr,pdf,dev]'" not in text
    assert (
        'dependency_source="/tmp/ocr-dependency-source-${GITHUB_RUN_ID}"'
        in text
    )
    assert 'git archive HEAD | tar -x -C "$dependency_source"' in text
    assert (
        'python -m pip install '
        '"$dependency_source[historical-ocr,pdf,dev]"'
        in text
    )
    assert 'rm -rf "$dependency_source"' in text


def test_primary_clean_gate_runs_after_isolated_install() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    install_at = text.index(
        "Install OCR and test dependencies outside primary checkout"
    )
    clean_at = text.index(
        "Prove primary checkout is clean and snapshot the complete data tree"
    )
    assert install_at < clean_at
