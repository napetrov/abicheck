from __future__ import annotations

from pathlib import Path

from abicheck.checker_policy import (
    BREAKING_KINDS,
    COMPATIBLE_KINDS,
    POLICY_REGISTRY,
    SOURCE_BREAK_KINDS,
    ChangeKind,
)


def test_policy_sets_are_disjoint_and_complete() -> None:
    assert not (BREAKING_KINDS & COMPATIBLE_KINDS)
    assert not (BREAKING_KINDS & SOURCE_BREAK_KINDS)
    assert not (COMPATIBLE_KINDS & SOURCE_BREAK_KINDS)

    classified = BREAKING_KINDS | COMPATIBLE_KINDS | SOURCE_BREAK_KINDS
    assert classified == set(ChangeKind)


def test_policy_registry_matches_enum() -> None:
    assert set(POLICY_REGISTRY) == set(ChangeKind)


def test_readme_mentions_all_verdict_levels() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    assert "NO_CHANGE" in text
    assert "COMPATIBLE" in text
    assert "BREAKING" in text
    assert "Source-level" in text or "source-level" in text
