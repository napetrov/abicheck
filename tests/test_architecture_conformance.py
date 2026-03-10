from __future__ import annotations

from pathlib import Path

from abicheck.checker_policy import (
    API_BREAK_KINDS,
    BREAKING_KINDS,
    COMPATIBLE_KINDS,
    POLICY_REGISTRY,
    ChangeKind,
)


def test_policy_sets_are_disjoint_and_complete() -> None:
    assert not (BREAKING_KINDS & COMPATIBLE_KINDS)
    assert not (BREAKING_KINDS & API_BREAK_KINDS)
    assert not (COMPATIBLE_KINDS & API_BREAK_KINDS)

    classified = BREAKING_KINDS | COMPATIBLE_KINDS | API_BREAK_KINDS
    assert classified == set(ChangeKind)


def test_policy_registry_matches_enum() -> None:
    assert set(POLICY_REGISTRY) == set(ChangeKind)


def test_readme_mentions_all_verdict_levels() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    assert "NO_CHANGE" in text
    assert "COMPATIBLE" in text
    assert "BREAKING" in text
    assert "Source-level" in text or "source-level" in text
