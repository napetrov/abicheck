"""Tests for appcompat HTML report generator."""
from __future__ import annotations

from types import SimpleNamespace

from abicheck.appcompat_html import appcompat_to_html
from abicheck.checker import Verdict


def _appcompat_result(
    verdict: Verdict = Verdict.COMPATIBLE,
    breaking: list | None = None,
    irrelevant: list | None = None,
    missing: list | None = None,
    missing_versions: list | None = None,
    with_metadata: bool = False,
) -> object:
    full_diff = SimpleNamespace(
        verdict=verdict,
        policy="strict_abi",
        old_metadata=None,
        new_metadata=None,
        confidence=None,
        evidence_tiers=[],
        coverage_warnings=[],
    )
    if with_metadata:
        full_diff.old_metadata = SimpleNamespace(
            path="/old/lib.so", sha256="aa" * 32, size_bytes=4096
        )
        full_diff.new_metadata = SimpleNamespace(
            path="/new/lib.so", sha256="bb" * 32, size_bytes=8192
        )
        full_diff.confidence = SimpleNamespace(value="medium")
        full_diff.evidence_tiers = ["elf", "header"]

    return SimpleNamespace(
        app_path="/bin/myapp",
        old_lib_path="/old/lib.so",
        new_lib_path="/new/lib.so",
        verdict=verdict,
        symbol_coverage=95.0,
        required_symbol_count=20,
        missing_symbols=missing or [],
        missing_versions=missing_versions or [],
        breaking_for_app=breaking or [],
        irrelevant_for_app=irrelevant or [],
        full_diff=full_diff,
    )


def test_html_is_valid_document() -> None:
    out = appcompat_to_html(_appcompat_result())
    assert out.startswith("<!DOCTYPE html>")
    assert "</html>" in out


def test_html_contains_verdict() -> None:
    out = appcompat_to_html(_appcompat_result(Verdict.BREAKING))
    assert "BREAKING" in out


def test_html_contains_app_path() -> None:
    out = appcompat_to_html(_appcompat_result())
    assert "/bin/myapp" in out


def test_html_contains_library_paths() -> None:
    out = appcompat_to_html(_appcompat_result())
    assert "/old/lib.so" in out
    assert "/new/lib.so" in out


def test_html_shows_symbol_coverage() -> None:
    out = appcompat_to_html(_appcompat_result())
    assert "95%" in out
    assert "20 required symbols" in out


def test_html_shows_missing_symbols() -> None:
    out = appcompat_to_html(_appcompat_result(missing=["foo", "bar"]))
    assert "Missing Symbols" in out
    assert "foo" in out
    assert "bar" in out


def test_html_shows_file_metadata() -> None:
    out = appcompat_to_html(_appcompat_result(with_metadata=True))
    assert "Library Files" in out
    assert "/old/lib.so" in out
    assert "4096" in out


def test_html_shows_confidence() -> None:
    out = appcompat_to_html(_appcompat_result(with_metadata=True))
    assert "Analysis Confidence" in out
    assert "MEDIUM" in out
    assert "elf" in out


def test_html_shows_no_relevant_changes() -> None:
    from enum import Enum

    class K(str, Enum):
        V = "func_added"

    change = SimpleNamespace(
        kind=K.V, symbol="new_func", description="added",
        old_value=None, new_value=None, source_location=None,
        affected_symbols=None, caused_by_type=None, caused_count=0,
        demangled_symbol="new_func",
    )
    out = appcompat_to_html(_appcompat_result(irrelevant=[change]))
    assert "No Relevant Changes" in out
    assert "Irrelevant Changes" in out
