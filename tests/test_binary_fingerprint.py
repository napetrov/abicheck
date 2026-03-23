"""Tests for abicheck.binary_fingerprint — function fingerprinting and rename detection.

All test data is synthetic — no real binaries required for the unit tests.
Integration tests that use real ELF binaries are marked @pytest.mark.integration.
"""
from __future__ import annotations

import pytest

from abicheck.binary_fingerprint import (
    _MIN_SYMBOL_SIZE,
    BinarySummary,
    FunctionFingerprint,
    SectionSummary,
    match_renamed_functions,
)
from abicheck.checker import ChangeKind, compare
from abicheck.elf_metadata import ElfMetadata, ElfSymbol, SymbolBinding, SymbolType
from abicheck.model import AbiSnapshot, Function, Visibility

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fp(name: str, size: int, code_hash: str = "") -> FunctionFingerprint:
    """Shorthand for creating a FunctionFingerprint."""
    return FunctionFingerprint(name=name, size=size, code_hash=code_hash)


def _snap_elf_only(
    version: str,
    symbols: list[ElfSymbol],
    functions: list[Function] | None = None,
) -> AbiSnapshot:
    """Create an elf_only_mode snapshot with ELF symbols."""
    if functions is None:
        functions = [
            Function(
                name=s.name, mangled=s.name, return_type="void",
                visibility=Visibility.ELF_ONLY,
            )
            for s in symbols
        ]
    return AbiSnapshot(
        library="libtest.so.1",
        version=version,
        functions=functions,
        elf=ElfMetadata(symbols=symbols),
        elf_only_mode=True,
    )


def _func_sym(name: str, size: int = 100) -> ElfSymbol:
    """Create an exported FUNC ElfSymbol."""
    return ElfSymbol(
        name=name,
        binding=SymbolBinding.GLOBAL,
        sym_type=SymbolType.FUNC,
        size=size,
    )


# ---------------------------------------------------------------------------
# FunctionFingerprint model tests
# ---------------------------------------------------------------------------

class TestFunctionFingerprint:
    def test_frozen(self) -> None:
        fp = _fp("foo", 100, "abc")
        with pytest.raises(AttributeError):
            fp.name = "bar"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = _fp("foo", 100, "abc")
        b = _fp("foo", 100, "abc")
        assert a == b

    def test_inequality_name(self) -> None:
        assert _fp("foo", 100) != _fp("bar", 100)

    def test_inequality_size(self) -> None:
        assert _fp("foo", 100) != _fp("foo", 200)


# ---------------------------------------------------------------------------
# BinarySummary tests
# ---------------------------------------------------------------------------

class TestBinarySummary:
    def test_differs_from_identical(self) -> None:
        s = BinarySummary(sections={
            ".text": SectionSummary(".text", 1000, "aaa"),
            ".rodata": SectionSummary(".rodata", 200, "bbb"),
        })
        assert s.differs_from(s) == {}

    def test_differs_from_changed(self) -> None:
        old = BinarySummary(sections={
            ".text": SectionSummary(".text", 1000, "aaa"),
            ".rodata": SectionSummary(".rodata", 200, "bbb"),
        })
        new = BinarySummary(sections={
            ".text": SectionSummary(".text", 1000, "ccc"),
            ".rodata": SectionSummary(".rodata", 200, "bbb"),
        })
        diffs = old.differs_from(new)
        assert ".text" in diffs
        assert ".rodata" not in diffs
        assert diffs[".text"] == ("aaa", "ccc")

    def test_differs_from_sections_only_in_one(self) -> None:
        """Sections only in one binary are not reported as diffs."""
        old = BinarySummary(sections={
            ".text": SectionSummary(".text", 1000, "aaa"),
        })
        new = BinarySummary(sections={
            ".text": SectionSummary(".text", 1000, "aaa"),
            ".data": SectionSummary(".data", 100, "ddd"),
        })
        assert old.differs_from(new) == {}

    def test_text_size(self) -> None:
        s = BinarySummary(sections={
            ".text": SectionSummary(".text", 42, "x"),
        })
        assert s.text_size == 42

    def test_text_size_absent(self) -> None:
        assert BinarySummary().text_size is None


# ---------------------------------------------------------------------------
# match_renamed_functions tests
# ---------------------------------------------------------------------------

class TestMatchRenamedFunctions:
    def test_no_changes(self) -> None:
        """Same symbols in both → no rename candidates."""
        fps = {"foo": _fp("foo", 100, "aaa"), "bar": _fp("bar", 200, "bbb")}
        assert match_renamed_functions(fps, fps) == []

    def test_exact_match_size_and_hash(self) -> None:
        """Identical size + hash → confidence 1.0."""
        old = {"old_func": _fp("old_func", 128, "deadbeef")}
        new = {"new_func": _fp("new_func", 128, "deadbeef")}
        result = match_renamed_functions(old, new)
        assert len(result) == 1
        assert result[0].old_name == "old_func"
        assert result[0].new_name == "new_func"
        assert result[0].confidence == 1.0

    def test_size_only_match(self) -> None:
        """Same size, no code hash → confidence 0.8."""
        old = {"old_func": _fp("old_func", 128)}
        new = {"new_func": _fp("new_func", 128)}
        result = match_renamed_functions(old, new)
        assert len(result) == 1
        assert result[0].confidence == 0.8

    def test_fuzzy_size_match(self) -> None:
        """Size within 5% tolerance, unique match → confidence 0.5."""
        old = {"old_func": _fp("old_func", 100)}
        new = {"new_func": _fp("new_func", 104)}  # 4% difference
        result = match_renamed_functions(old, new)
        assert len(result) == 1
        assert result[0].confidence == 0.5

    def test_no_fuzzy_match_beyond_tolerance(self) -> None:
        """Size difference > 5% → no match."""
        old = {"old_func": _fp("old_func", 100)}
        new = {"new_func": _fp("new_func", 110)}  # 10% difference
        result = match_renamed_functions(old, new)
        assert len(result) == 0

    def test_common_symbols_excluded(self) -> None:
        """Symbols present in both old and new are not candidates."""
        old = {
            "common": _fp("common", 100, "aaa"),
            "old_only": _fp("old_only", 200, "bbb"),
        }
        new = {
            "common": _fp("common", 100, "aaa"),
            "new_only": _fp("new_only", 200, "bbb"),
        }
        result = match_renamed_functions(old, new)
        assert len(result) == 1
        assert result[0].old_name == "old_only"
        assert result[0].new_name == "new_only"

    def test_small_symbols_filtered(self) -> None:
        """Symbols smaller than _MIN_SYMBOL_SIZE are skipped."""
        old = {"tiny": _fp("tiny", _MIN_SYMBOL_SIZE - 1, "aaa")}
        new = {"renamed_tiny": _fp("renamed_tiny", _MIN_SYMBOL_SIZE - 1, "aaa")}
        assert match_renamed_functions(old, new) == []

    def test_ambiguous_size_match_skipped(self) -> None:
        """Multiple candidates with same size → no match (ambiguous)."""
        old = {"old_func": _fp("old_func", 128)}
        new = {
            "candidate_a": _fp("candidate_a", 128),
            "candidate_b": _fp("candidate_b", 128),
        }
        result = match_renamed_functions(old, new)
        assert len(result) == 0

    def test_hash_mismatch_prevents_size_only_match(self) -> None:
        """Same size but different code hashes → no size-only match."""
        old = {"old_func": _fp("old_func", 128, "aaaa")}
        new = {"new_func": _fp("new_func", 128, "bbbb")}
        result = match_renamed_functions(old, new)
        assert len(result) == 0

    def test_multiple_renames(self) -> None:
        """Multiple rename candidates matched correctly."""
        old = {
            "libfoo_v1_create": _fp("libfoo_v1_create", 256, "hash1"),
            "libfoo_v1_destroy": _fp("libfoo_v1_destroy", 128, "hash2"),
        }
        new = {
            "libfoo_create": _fp("libfoo_create", 256, "hash1"),
            "libfoo_destroy": _fp("libfoo_destroy", 128, "hash2"),
        }
        result = match_renamed_functions(old, new)
        assert len(result) == 2
        names = {(r.old_name, r.new_name) for r in result}
        assert ("libfoo_v1_create", "libfoo_create") in names
        assert ("libfoo_v1_destroy", "libfoo_destroy") in names

    def test_greedy_matching_one_to_one(self) -> None:
        """Each symbol is matched at most once (greedy 1:1)."""
        old = {
            "a": _fp("a", 100, "hash_x"),
            "b": _fp("b", 100, "hash_x"),  # same hash as 'a'
        }
        new = {
            "c": _fp("c", 100, "hash_x"),
        }
        result = match_renamed_functions(old, new)
        # Only one match possible (1:1)
        assert len(result) == 1

    def test_empty_inputs(self) -> None:
        assert match_renamed_functions({}, {}) == []
        assert match_renamed_functions({"a": _fp("a", 100)}, {}) == []
        assert match_renamed_functions({}, {"b": _fp("b", 100)}) == []

    def test_sorted_by_confidence(self) -> None:
        """Results are sorted by confidence descending."""
        old = {
            "exact_old": _fp("exact_old", 200, "hash_e"),
            "fuzzy_old": _fp("fuzzy_old", 100),
        }
        new = {
            "exact_new": _fp("exact_new", 200, "hash_e"),
            "fuzzy_new": _fp("fuzzy_new", 104),
        }
        result = match_renamed_functions(old, new)
        assert len(result) == 2
        assert result[0].confidence >= result[1].confidence


# ---------------------------------------------------------------------------
# Detector integration tests (using compare())
# ---------------------------------------------------------------------------

class TestFingerprintRenameDetector:
    """Test the fingerprint_renames detector via the full compare() pipeline."""

    def test_likely_renamed_detected_in_elf_only_mode(self) -> None:
        """Renamed function with same size is detected as FUNC_LIKELY_RENAMED."""
        old = _snap_elf_only("1.0", [_func_sym("libfoo_v1_create", 256)])
        new = _snap_elf_only("2.0", [_func_sym("libfoo_create", 256)])
        result = compare(old, new)

        rename_changes = [c for c in result.changes if c.kind == ChangeKind.FUNC_LIKELY_RENAMED]
        assert len(rename_changes) == 1
        assert rename_changes[0].old_value == "libfoo_v1_create"
        assert rename_changes[0].new_value == "libfoo_create"

    def test_not_triggered_without_elf_only_mode(self) -> None:
        """Detector is gated behind elf_only_mode — disabled for header-based analysis."""
        old = AbiSnapshot(
            library="libtest.so.1", version="1.0",
            functions=[Function(name="old_func", mangled="old_func",
                                return_type="void", visibility=Visibility.PUBLIC)],
            elf=ElfMetadata(symbols=[_func_sym("old_func", 256)]),
            elf_only_mode=False,
        )
        new = AbiSnapshot(
            library="libtest.so.1", version="2.0",
            functions=[Function(name="new_func", mangled="new_func",
                                return_type="void", visibility=Visibility.PUBLIC)],
            elf=ElfMetadata(symbols=[_func_sym("new_func", 256)]),
            elf_only_mode=False,
        )
        result = compare(old, new)
        rename_changes = [c for c in result.changes if c.kind == ChangeKind.FUNC_LIKELY_RENAMED]
        assert len(rename_changes) == 0

    def test_not_triggered_without_elf_metadata(self) -> None:
        """Detector requires ELF metadata — disabled for PE/Mach-O."""
        old = AbiSnapshot(
            library="libtest.so.1", version="1.0",
            functions=[Function(name="old_func", mangled="old_func",
                                return_type="void", visibility=Visibility.ELF_ONLY)],
            elf_only_mode=True,
        )
        new = AbiSnapshot(
            library="libtest.so.1", version="2.0",
            functions=[Function(name="new_func", mangled="new_func",
                                return_type="void", visibility=Visibility.ELF_ONLY)],
            elf_only_mode=True,
        )
        result = compare(old, new)
        rename_changes = [c for c in result.changes if c.kind == ChangeKind.FUNC_LIKELY_RENAMED]
        assert len(rename_changes) == 0

    def test_small_symbols_not_matched(self) -> None:
        """Tiny functions (stubs) should not produce rename matches."""
        old = _snap_elf_only("1.0", [_func_sym("stub_old", 4)])
        new = _snap_elf_only("2.0", [_func_sym("stub_new", 4)])
        result = compare(old, new)
        rename_changes = [c for c in result.changes if c.kind == ChangeKind.FUNC_LIKELY_RENAMED]
        assert len(rename_changes) == 0

    def test_different_sizes_not_matched(self) -> None:
        """Functions with significantly different sizes should not match."""
        old = _snap_elf_only("1.0", [_func_sym("func_old", 100)])
        new = _snap_elf_only("2.0", [_func_sym("func_new", 200)])
        result = compare(old, new)
        rename_changes = [c for c in result.changes if c.kind == ChangeKind.FUNC_LIKELY_RENAMED]
        assert len(rename_changes) == 0

    def test_multiple_renames_detected(self) -> None:
        """Multiple renames in a single comparison are all detected."""
        old_syms = [_func_sym("v1_init", 256), _func_sym("v1_cleanup", 128)]
        new_syms = [_func_sym("v2_init", 256), _func_sym("v2_cleanup", 128)]
        old = _snap_elf_only("1.0", old_syms)
        new = _snap_elf_only("2.0", new_syms)
        result = compare(old, new)

        rename_changes = [c for c in result.changes if c.kind == ChangeKind.FUNC_LIKELY_RENAMED]
        assert len(rename_changes) == 2

    def test_unchanged_functions_not_affected(self) -> None:
        """Functions present in both versions are not reported as renames."""
        shared_sym = _func_sym("shared_func", 300)
        old = _snap_elf_only("1.0", [shared_sym, _func_sym("old_only", 128)])
        new = _snap_elf_only("2.0", [shared_sym, _func_sym("new_only", 128)])
        result = compare(old, new)

        rename_changes = [c for c in result.changes if c.kind == ChangeKind.FUNC_LIKELY_RENAMED]
        assert len(rename_changes) == 1
        assert rename_changes[0].old_value == "old_only"
        assert rename_changes[0].new_value == "new_only"
