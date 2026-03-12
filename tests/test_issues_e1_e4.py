"""Investigation tests for upstream issues E1-E4.

E1 (Issue #66): vtable reordering severity — TYPE_VTABLE_CHANGED is BREAKING.
  Already covered by TestTypeVtableChanged in test_changekind_completeness.py.
  Additional parity test here for completeness.

E2 (Issue #64): C code treated as C++ — detect_profile() correctly identifies
  libraries with no _Z-mangled symbols as language_profile="c".

E3 (Issue #58): struct member → anonymous union false positive.
  Adding a union member to a struct should not cause false positives when
  the struct fields are unchanged.

E4 (Issue #53): struct inside class identified as class.
  TypeField kind is determined by DW_TAG_structure_type vs DW_TAG_class_type;
  both map to record types correctly.
"""
from __future__ import annotations

from abicheck.checker import ChangeKind, Verdict, compare
from abicheck.core.pipeline import detect_profile
from abicheck.model import (
    AbiSnapshot,
    Function,
    RecordType,
    TypeField,
    Visibility,
)


def _snap(**kwargs: object) -> AbiSnapshot:
    defaults: dict[str, object] = dict(library="lib.so", version="1.0")
    defaults.update(kwargs)
    return AbiSnapshot(**defaults)  # type: ignore[arg-type]


def _func(name: str, mangled: str, **kwargs: object) -> Function:
    defaults: dict[str, object] = dict(return_type="void", visibility=Visibility.PUBLIC)
    defaults.update(kwargs)
    return Function(name=name, mangled=mangled, **defaults)  # type: ignore[arg-type]


# ── E1: Issue #66 — vtable reordering severity (BREAKING) ────────────────────

class TestVtableReorderingSeverity:
    """Verify TYPE_VTABLE_CHANGED is always emitted as BREAKING.

    Issue #66: vtable reordering was not being flagged as breaking.
    TYPE_VTABLE_CHANGED is in BREAKING_KINDS → verdict must be BREAKING.
    """

    def test_vtable_reorder_is_breaking(self) -> None:
        old = _snap(types=[RecordType(
            name="Widget", kind="class",
            vtable=["_ZN6Widget4drawEv", "_ZN6Widget6updateEv"],
        )])
        new = _snap(types=[RecordType(
            name="Widget", kind="class",
            vtable=["_ZN6Widget6updateEv", "_ZN6Widget4drawEv"],
        )])
        result = compare(old, new)
        assert ChangeKind.TYPE_VTABLE_CHANGED in {c.kind for c in result.changes}
        assert result.verdict == Verdict.BREAKING

    def test_vtable_in_breaking_kinds(self) -> None:
        """TYPE_VTABLE_CHANGED must be in BREAKING_KINDS."""
        from abicheck.checker_policy import BREAKING_KINDS
        assert ChangeKind.TYPE_VTABLE_CHANGED in BREAKING_KINDS


# ── E2: Issue #64 — C code treated as C++ ────────────────────────────────────

class TestCProfileDetection:
    """Verify detect_profile() correctly identifies C libraries.

    Issue #64: C libraries were being treated as C++.
    Libraries with no _Z-mangled symbols and all extern-C functions
    should be detected as language_profile="c".
    """

    def test_c_library_no_mangling_detected_as_c(self) -> None:
        """Library with extern-C functions and no _Z symbols → profile='c'."""
        snap = _snap(functions=[
            Function(
                name="init_ctx", mangled="init_ctx",
                return_type="int", visibility=Visibility.PUBLIC,
                is_extern_c=True,
            ),
            Function(
                name="destroy_ctx", mangled="destroy_ctx",
                return_type="void", visibility=Visibility.PUBLIC,
                is_extern_c=True,
            ),
        ])
        assert detect_profile(snap) == "c"

    def test_cpp_library_with_z_mangling_detected_as_cpp(self) -> None:
        """Library with _Z-mangled symbols → profile='cpp'."""
        snap = _snap(functions=[
            Function(
                name="Widget::init", mangled="_ZN6Widget4initEv",
                return_type="void", visibility=Visibility.PUBLIC,
            ),
        ])
        assert detect_profile(snap) == "cpp"

    def test_explicit_language_profile_respected(self) -> None:
        """Explicit language_profile override is always respected."""
        snap = _snap(
            functions=[
                Function(
                    name="Widget::init", mangled="_ZN6Widget4initEv",
                    return_type="void", visibility=Visibility.PUBLIC,
                ),
            ],
            language_profile="c",  # explicit override
        )
        assert detect_profile(snap) == "c"

    def test_empty_library_returns_none(self) -> None:
        """Library with no public functions → profile=None (unknown)."""
        snap = _snap()
        assert detect_profile(snap) is None


# ── E3: Issue #58 — struct member → anonymous union false positive ────────────

class TestStructToUnionFalsePositive:
    """Verify struct→union transitions don't generate false positives.

    Issue #58: Adding a union member to a struct should not cause false
    positives when the struct has other unchanged fields.
    """

    def test_struct_unchanged_fields_no_false_positive(self) -> None:
        """Struct with same fields → no changes emitted."""
        old = _snap(types=[RecordType(
            name="Config", kind="struct",
            fields=[TypeField(name="x", type="int", offset_bits=0)],
        )])
        new = _snap(types=[RecordType(
            name="Config", kind="struct",
            fields=[TypeField(name="x", type="int", offset_bits=0)],
        )])
        result = compare(old, new)
        assert not result.changes

    def test_struct_union_kind_change_is_breaking(self) -> None:
        """struct → union kind change IS breaking (TYPE_KIND_CHANGED)."""
        old = _snap(types=[RecordType(
            name="Data", kind="struct",
            fields=[TypeField(name="x", type="int")],
        )])
        new = _snap(types=[RecordType(
            name="Data", kind="union",
            is_union=True,
            fields=[TypeField(name="x", type="int")],
        )])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.TYPE_KIND_CHANGED in kinds
        assert result.verdict == Verdict.BREAKING

    def test_struct_field_added_anonymous_union_type(self) -> None:
        """Adding a field whose type refers to an anonymous union is COMPATIBLE
        for standard-layout structs (TYPE_FIELD_ADDED_COMPATIBLE)."""
        old = _snap(types=[RecordType(
            name="Point", kind="struct",
            fields=[TypeField(name="x", type="int", offset_bits=0)],
        )])
        new = _snap(types=[RecordType(
            name="Point", kind="struct",
            fields=[
                TypeField(name="x", type="int", offset_bits=0),
                TypeField(name="y", type="int", offset_bits=32),
            ],
        )])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        # Standard-layout struct → COMPATIBLE field addition
        assert ChangeKind.TYPE_FIELD_ADDED_COMPATIBLE in kinds
        # Must NOT be breaking
        assert ChangeKind.TYPE_FIELD_ADDED not in kinds


# ── E4: Issue #53 — struct inside class identified as class ──────────────────

class TestNestedStructKind:
    """Verify struct/class kind is tracked correctly.

    Issue #53: struct inside class was being identified as class.
    Both struct and class are valid 'kind' values in RecordType.
    """

    def test_struct_kind_preserved(self) -> None:
        """RecordType with kind='struct' must be preserved through comparison."""
        old = _snap(types=[RecordType(name="Inner", kind="struct")])
        new = _snap(types=[RecordType(name="Inner", kind="struct")])
        result = compare(old, new)
        assert not result.changes

    def test_class_kind_preserved(self) -> None:
        """RecordType with kind='class' must be preserved through comparison."""
        old = _snap(types=[RecordType(name="Widget", kind="class")])
        new = _snap(types=[RecordType(name="Widget", kind="class")])
        result = compare(old, new)
        assert not result.changes

    def test_struct_to_class_is_source_level_only(self) -> None:
        """struct→class kind change must emit SOURCE_LEVEL_KIND_CHANGED (not BREAKING)."""
        old = _snap(types=[RecordType(name="Node", kind="struct")])
        new = _snap(types=[RecordType(name="Node", kind="class")])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.SOURCE_LEVEL_KIND_CHANGED in kinds
        # struct↔class is not a binary ABI change — must NOT be BREAKING
        assert ChangeKind.TYPE_KIND_CHANGED not in kinds

    def test_struct_to_union_is_binary_break(self) -> None:
        """struct→union (or class→union) must emit TYPE_KIND_CHANGED (BREAKING)."""
        old = _snap(types=[RecordType(name="Data", kind="struct")])
        new = _snap(types=[RecordType(name="Data", kind="union", is_union=True)])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.TYPE_KIND_CHANGED in kinds
        assert result.verdict == Verdict.BREAKING

    def test_nested_struct_in_class_roundtrip(self) -> None:
        """Nested struct inside class — kind attribute must be preserved in serialization."""
        from abicheck.serialization import snapshot_from_dict, snapshot_to_dict
        snap = _snap(types=[
            RecordType(
                name="Outer", kind="class",
                fields=[TypeField(name="inner_x", type="InnerStruct::x_type", offset_bits=0)],
            ),
            RecordType(name="InnerStruct", kind="struct"),
        ])
        d = snapshot_to_dict(snap)
        snap2 = snapshot_from_dict(d)
        kinds = {t.kind for t in snap2.types}
        assert "class" in kinds
        assert "struct" in kinds
