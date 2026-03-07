"""Tests for suppression file support."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from abicheck.checker import Change, ChangeKind, DiffResult, Verdict, compare
from abicheck.suppression import Suppression, SuppressionList


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_change(kind: ChangeKind, symbol: str, description: str = "desc") -> Change:
    return Change(kind=kind, symbol=symbol, description=description)


def write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "suppressions.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ─── test 1: load valid suppression file ──────────────────────────────────────

def test_load_valid_file(tmp_path: Path) -> None:
    yaml_path = write_yaml(tmp_path, """
        version: 1
        suppressions:
          - symbol: "_ZN3foo3barEv"
            change_kind: "func_removed"
            reason: "intentional"
          - symbol_pattern: ".*detail.*"
            reason: "internal namespace"
    """)
    sl = SuppressionList.load(yaml_path)
    assert len(sl) == 2


# ─── test 2: exact symbol match ───────────────────────────────────────────────

def test_exact_symbol_match() -> None:
    sup = Suppression(symbol="_ZN3foo3barEv")
    change = make_change(ChangeKind.FUNC_REMOVED, "_ZN3foo3barEv")
    assert sup.matches(change)


def test_exact_symbol_no_match() -> None:
    sup = Suppression(symbol="_ZN3foo3barEv")
    change = make_change(ChangeKind.FUNC_REMOVED, "_ZN3foo3bazEv")
    assert not sup.matches(change)


# ─── test 3: pattern match ────────────────────────────────────────────────────

def test_pattern_match() -> None:
    sup = Suppression(symbol_pattern=".*detail.*")
    change = make_change(ChangeKind.FUNC_REMOVED, "_ZN3fooNdetailE3barEv")
    assert sup.matches(change)


def test_pattern_no_match() -> None:
    sup = Suppression(symbol_pattern=".*detail.*")
    change = make_change(ChangeKind.FUNC_REMOVED, "_ZN3foo3barEv")
    assert not sup.matches(change)


# ─── test 4: change_kind filtering ───────────────────────────────────────────

def test_change_kind_match() -> None:
    sup = Suppression(symbol="_ZN3foo3barEv", change_kind="func_removed")
    change = make_change(ChangeKind.FUNC_REMOVED, "_ZN3foo3barEv")
    assert sup.matches(change)


def test_change_kind_mismatch() -> None:
    """Symbol matches but change_kind does not — should NOT be suppressed."""
    sup = Suppression(symbol="_ZN3foo3barEv", change_kind="func_removed")
    change = make_change(ChangeKind.FUNC_RETURN_CHANGED, "_ZN3foo3barEv")
    assert not sup.matches(change)


# ─── test 5: suppressed_count in DiffResult ──────────────────────────────────

def test_suppressed_count_in_diff_result(tmp_path: Path) -> None:
    """compare() with suppression decrements visible changes and increments suppressed_count."""
    from abicheck.model import AbiSnapshot

    yaml_path = write_yaml(tmp_path, """
        version: 1
        suppressions:
          - symbol: "_ZN3foo3barEv"
            change_kind: "func_removed"
    """)
    sl = SuppressionList.load(yaml_path)

    # Build minimal snapshots: old has a function, new does not.
    old = AbiSnapshot(library="libfoo", version="1.0")
    new = AbiSnapshot(library="libfoo", version="2.0")

    from abicheck.model import Function, Visibility
    old.functions.append(
        Function(
            name="foo::bar",
            mangled="_ZN3foo3barEv",
            return_type="void",
            visibility=Visibility.PUBLIC,
        )
    )

    result = compare(old, new, suppression=sl)
    assert result.suppressed_count == 1
    # The suppressed change is removed from changes list
    assert all(c.symbol != "_ZN3foo3barEv" for c in result.changes)


# ─── test 6: invalid YAML raises ValueError ───────────────────────────────────

def test_invalid_yaml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 2\nsuppressions: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        SuppressionList.load(bad)


def test_missing_symbol_raises() -> None:
    with pytest.raises(ValueError):
        Suppression(symbol=None, symbol_pattern=None)


def test_both_symbol_and_pattern_raises() -> None:
    with pytest.raises(ValueError):
        Suppression(symbol="foo", symbol_pattern="bar")


def test_invalid_yaml_syntax(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(": :\n  - bad: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError):
        SuppressionList.load(bad)
