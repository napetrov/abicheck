from abicheck.checker import Change, ChangeKind, DiffResult, Verdict
from abicheck.checker_policy import policy_for, policy_registry_markdown
from abicheck.report_summary import build_summary, compatibility_metrics


def test_policy_registry_has_doc_slug_and_severity() -> None:
    entry = policy_for(ChangeKind.FUNC_REMOVED)
    assert entry.doc_slug == "func_removed"
    assert entry.severity == "error"


def test_policy_registry_markdown_contains_header() -> None:
    md = policy_registry_markdown()
    assert "| ChangeKind | Default verdict | Severity | Doc slug |" in md
    assert "`func_removed`" in md


def test_summary_metrics_include_percentages() -> None:
    result = DiffResult(
        old_version="1.0",
        new_version="2.0",
        library="libx.so",
        changes=[Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "removed")],
        verdict=Verdict.BREAKING,
    )
    summary = build_summary(result)
    assert summary.binary_compatibility_pct == 0.0
    assert summary.affected_pct == 0.0


def test_compatibility_metrics_use_old_symbol_count() -> None:
    metrics = compatibility_metrics(
        [Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "removed")],
        old_symbol_count=10,
    )
    assert metrics.breaking_count == 1
    assert round(metrics.binary_compatibility_pct, 1) == 90.0
    assert round(metrics.affected_pct, 1) == 10.0
