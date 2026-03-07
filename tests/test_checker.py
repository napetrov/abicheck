"""Tests for abi_check.checker — pure Python, no external tools required.

All test fixtures are original C++ snippets authored for this project.
No code or test data is derived from abi-compliance-checker (LGPL-2.1).
"""
import pytest

from abi_check.checker import ChangeKind, Verdict, compare
from abi_check.model import (
    AbiSnapshot, Function, Param, ParamKind, RecordType,
    TypeField, Variable, Visibility,
)


def _snap(version: str, functions=None, variables=None, types=None) -> AbiSnapshot:
    return AbiSnapshot(
        library="libtest.so.1",
        version=version,
        functions=functions or [],
        variables=variables or [],
        types=types or [],
    )


def _pub_func(name: str, mangled: str, ret: str = "void",
              params=None, virtual=False, noexcept=False) -> Function:
    return Function(
        name=name, mangled=mangled, return_type=ret,
        params=params or [], visibility=Visibility.PUBLIC,
        is_virtual=virtual, is_noexcept=noexcept,
    )


def _pub_var(name: str, mangled: str, type_: str) -> Variable:
    return Variable(name=name, mangled=mangled, type=type_,
                    visibility=Visibility.PUBLIC)


# ── No change ────────────────────────────────────────────────────────────────

class TestNoChange:
    def test_identical_snapshots(self):
        f = _pub_func("init", "_Z4initv", "int")
        old = _snap("1.0", functions=[f])
        new = _snap("1.1", functions=[f])
        r = compare(old, new)
        assert r.verdict == Verdict.NO_CHANGE
        assert r.changes == []

    def test_empty_snapshots(self):
        r = compare(_snap("1.0"), _snap("1.1"))
        assert r.verdict == Verdict.NO_CHANGE


# ── Function removal ─────────────────────────────────────────────────────────

class TestFunctionRemoval:
    def test_public_func_removed_is_breaking(self):
        f = _pub_func("process", "_Z7processv")
        old = _snap("1.0", functions=[f])
        new = _snap("2.0", functions=[])
        r = compare(old, new)
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.FUNC_REMOVED for c in r.changes)

    def test_hidden_func_removal_is_not_reported(self):
        f = Function(name="internal", mangled="_Z8internalv",
                     return_type="void", visibility=Visibility.HIDDEN)
        old = _snap("1.0", functions=[f])
        new = _snap("2.0", functions=[])
        r = compare(old, new)
        assert r.verdict == Verdict.NO_CHANGE


# ── Function addition ─────────────────────────────────────────────────────────

class TestFunctionAddition:
    def test_new_public_func_is_compatible(self):
        f_old = _pub_func("init", "_Z4initv")
        f_new1 = _pub_func("init", "_Z4initv")
        f_new2 = _pub_func("reset", "_Z5resetv")
        old = _snap("1.0", functions=[f_old])
        new = _snap("1.1", functions=[f_new1, f_new2])
        r = compare(old, new)
        assert r.verdict == Verdict.COMPATIBLE
        assert any(c.kind == ChangeKind.FUNC_ADDED for c in r.changes)


# ── Return type change ────────────────────────────────────────────────────────

class TestReturnTypeChange:
    def test_return_type_changed_is_breaking(self):
        old_f = _pub_func("getCount", "_Z8getCountv", ret="int")
        new_f = _pub_func("getCount", "_Z8getCountv", ret="size_t")
        r = compare(_snap("1.0", [old_f]), _snap("2.0", [new_f]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.FUNC_RETURN_CHANGED for c in r.changes)


# ── Parameter changes ─────────────────────────────────────────────────────────

class TestParameterChanges:
    def test_param_type_change_is_breaking(self):
        old_f = _pub_func("send", "_Z4sendPv",
                          params=[Param(name="buf", type="void*")])
        new_f = _pub_func("send", "_Z4sendPv",
                          params=[Param(name="buf", type="const void*")])
        r = compare(_snap("1.0", [old_f]), _snap("2.0", [new_f]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.FUNC_PARAMS_CHANGED for c in r.changes)

    def test_param_added_is_breaking(self):
        old_f = _pub_func("open", "_Z4openv")
        new_f = _pub_func("open", "_Z4openv",
                          params=[Param(name="flags", type="int")])
        r = compare(_snap("1.0", [old_f]), _snap("2.0", [new_f]))
        assert r.verdict == Verdict.BREAKING


# ── noexcept specifier ────────────────────────────────────────────────────────

class TestNoexcept:
    def test_noexcept_removed_is_breaking(self):
        old_f = _pub_func("move", "_Z4movev", noexcept=True)
        new_f = _pub_func("move", "_Z4movev", noexcept=False)
        r = compare(_snap("1.0", [old_f]), _snap("2.0", [new_f]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.FUNC_NOEXCEPT_REMOVED for c in r.changes)

    def test_noexcept_added_is_breaking(self):  # C++17 P0012R1
        old_f = _pub_func("swap", "_Z4swapv", noexcept=False)
        new_f = _pub_func("swap", "_Z4swapv", noexcept=True)
        r = compare(_snap("1.0", [old_f]), _snap("2.0", [new_f]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.FUNC_NOEXCEPT_ADDED for c in r.changes)


# ── Virtual methods ───────────────────────────────────────────────────────────

class TestVirtualMethods:
    def test_become_virtual_is_breaking(self):
        old_f = _pub_func("render", "_Z6renderv", virtual=False)
        new_f = _pub_func("render", "_Z6renderv", virtual=True)
        r = compare(_snap("1.0", [old_f]), _snap("2.0", [new_f]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.FUNC_VIRTUAL_ADDED for c in r.changes)

    def test_lose_virtual_is_breaking(self):
        old_f = _pub_func("update", "_Z6updatev", virtual=True)
        new_f = _pub_func("update", "_Z6updatev", virtual=False)
        r = compare(_snap("1.0", [old_f]), _snap("2.0", [new_f]))
        assert r.verdict == Verdict.BREAKING


# ── Variables ─────────────────────────────────────────────────────────────────

class TestVariables:
    def test_var_removed_is_breaking(self):
        v = _pub_var("g_version", "_ZN3lib9g_versionE", "int")
        r = compare(_snap("1.0", variables=[v]), _snap("2.0", variables=[]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.VAR_REMOVED for c in r.changes)

    def test_var_type_changed_is_breaking(self):
        old_v = _pub_var("g_limit", "_ZN3lib7g_limitE", "int")
        new_v = _pub_var("g_limit", "_ZN3lib7g_limitE", "unsigned int")
        r = compare(_snap("1.0", variables=[old_v]), _snap("2.0", variables=[new_v]))
        assert r.verdict == Verdict.BREAKING

    def test_var_added_is_compatible(self):
        v_old = _pub_var("g_count", "_ZN3lib7g_countE", "int")
        v_new1 = _pub_var("g_count", "_ZN3lib7g_countE", "int")
        v_new2 = _pub_var("g_max", "_ZN3lib5g_maxE", "int")
        r = compare(_snap("1.0", variables=[v_old]),
                    _snap("1.1", variables=[v_new1, v_new2]))
        assert r.verdict == Verdict.COMPATIBLE


# ── Type / struct changes ─────────────────────────────────────────────────────

class TestTypeChanges:
    def _make_point(self, size=64) -> RecordType:
        return RecordType(
            name="Point", kind="struct", size_bits=size,
            fields=[
                TypeField("x", "float", offset_bits=0),
                TypeField("y", "float", offset_bits=32),
            ],
        )

    def test_struct_size_change_is_breaking(self):
        old_t = self._make_point(64)
        new_t = self._make_point(96)
        r = compare(_snap("1.0", types=[old_t]), _snap("2.0", types=[new_t]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.TYPE_SIZE_CHANGED for c in r.changes)

    def test_field_removed_is_breaking(self):
        old_t = self._make_point(64)
        new_t = RecordType(
            name="Point", kind="struct", size_bits=32,
            fields=[TypeField("x", "float", offset_bits=0)],
        )
        r = compare(_snap("1.0", types=[old_t]), _snap("2.0", types=[new_t]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.TYPE_FIELD_REMOVED for c in r.changes)

    def test_field_offset_changed_is_breaking(self):
        old_t = RecordType(
            name="Rect", kind="struct", size_bits=128,
            fields=[
                TypeField("x", "int", offset_bits=0),
                TypeField("y", "int", offset_bits=32),
                TypeField("w", "int", offset_bits=64),
                TypeField("h", "int", offset_bits=96),
            ],
        )
        new_t = RecordType(
            name="Rect", kind="struct", size_bits=160,
            fields=[
                TypeField("_pad", "int", offset_bits=0),   # inserted at front
                TypeField("x", "int", offset_bits=32),     # shifted
                TypeField("y", "int", offset_bits=64),
                TypeField("w", "int", offset_bits=96),
                TypeField("h", "int", offset_bits=128),
            ],
        )
        r = compare(_snap("1.0", types=[old_t]), _snap("2.0", types=[new_t]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.TYPE_FIELD_OFFSET_CHANGED for c in r.changes)

    def test_base_class_changed_is_breaking(self):
        old_t = RecordType(name="Derived", kind="class", bases=["Base"])
        new_t = RecordType(name="Derived", kind="class", bases=["OtherBase"])
        r = compare(_snap("1.0", types=[old_t]), _snap("2.0", types=[new_t]))
        assert r.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.TYPE_BASE_CHANGED for c in r.changes)

    def test_vtable_change_is_breaking(self):
        old_t = RecordType(name="Widget", kind="class",
                           vtable=["_ZN6Widget6renderEv", "_ZN6Widget6updateEv"])
        new_t = RecordType(name="Widget", kind="class",
                           vtable=["_ZN6Widget6updateEv", "_ZN6Widget6renderEv"])  # reordered
        r = compare(_snap("1.0", types=[old_t]), _snap("2.0", types=[new_t]))
        assert r.verdict == Verdict.BREAKING

    def test_type_removed_is_breaking(self):
        t = RecordType(name="Handle", kind="struct")
        r = compare(_snap("1.0", types=[t]), _snap("2.0", types=[]))
        assert r.verdict == Verdict.BREAKING

    def test_type_added_is_compatible(self):
        t = RecordType(name="NewConfig", kind="struct")
        r = compare(_snap("1.0", types=[]), _snap("1.1", types=[t]))
        assert r.verdict == Verdict.COMPATIBLE


# ── Verdict priority ──────────────────────────────────────────────────────────

class TestVerdictPriority:
    def test_breaking_overrides_compatible(self):
        """Mixed: one function added (compatible) + one removed (breaking) = BREAKING."""
        f_old = _pub_func("old_api", "_Z7old_apiv")
        f_kept = _pub_func("kept", "_Z4keptv")
        f_new = _pub_func("new_api", "_Z7new_apiv")
        old = _snap("1.0", functions=[f_old, f_kept])
        new = _snap("2.0", functions=[f_kept, f_new])
        r = compare(old, new)
        assert r.verdict == Verdict.BREAKING

    def test_noexcept_added_overrides_compatible(self):
        """noexcept added (source_break) + new func (compatible) = SOURCE_BREAK."""
        f_noexcept = _pub_func("swap", "_Z4swapv", noexcept=False)
        f_new = _pub_func("swap", "_Z4swapv", noexcept=True)
        f_added = _pub_func("reset", "_Z5resetv")
        old = _snap("1.0", functions=[f_noexcept])
        new = _snap("1.1", functions=[f_new, f_added])
        r = compare(old, new)
        assert r.verdict == Verdict.BREAKING
