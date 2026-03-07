"""Unit tests for Sprint 3 DWARF-aware layout diff."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from abicheck.checker import ChangeKind, Verdict, compare
from abicheck.dwarf_metadata import (
    DwarfMetadata,
    EnumInfo,
    FieldInfo,
    StructLayout,
    parse_dwarf_metadata,
)
from abicheck.model import AbiSnapshot

# ── helpers ──────────────────────────────────────────────────────────────────

def _snap(dwarf: DwarfMetadata | None) -> AbiSnapshot:
    snap = AbiSnapshot(library="libtest.so", version="v1")
    snap.dwarf = dwarf  # type: ignore[attr-defined]
    return snap


def _meta(**kwargs: object) -> DwarfMetadata:
    m = DwarfMetadata(has_dwarf=True)
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


def _struct(
    name: str,
    size: int,
    fields: list[FieldInfo] | None = None,
    alignment: int = 0,
    is_union: bool = False,
) -> StructLayout:
    return StructLayout(
        name=name,
        byte_size=size,
        alignment=alignment,
        fields=fields or [],
        is_union=is_union,
    )


def _field(name: str, type_name: str, offset: int, size: int) -> FieldInfo:
    return FieldInfo(name=name, type_name=type_name, byte_offset=offset, byte_size=size)


def _enum(name: str, byte_size: int, members: dict[str, int] | None = None) -> EnumInfo:
    return EnumInfo(name=name, underlying_byte_size=byte_size, members=members or {})


# ── no-DWARF graceful degradation ────────────────────────────────────────────

def test_no_dwarf_both_produces_no_changes() -> None:
    """If neither snapshot has DWARF, no DWARF changes produced."""
    old = _snap(None)
    new = _snap(None)
    result = compare(old, new)
    dwarf_kinds = {
        ChangeKind.STRUCT_SIZE_CHANGED,
        ChangeKind.STRUCT_FIELD_OFFSET_CHANGED,
        ChangeKind.STRUCT_FIELD_REMOVED,
        ChangeKind.STRUCT_FIELD_TYPE_CHANGED,
        ChangeKind.ENUM_UNDERLYING_SIZE_CHANGED,
        ChangeKind.ENUM_MEMBER_REMOVED,
        ChangeKind.ENUM_MEMBER_VALUE_CHANGED,
    }
    kinds = {c.kind for c in result.changes}
    assert kinds & dwarf_kinds == set()


def test_no_dwarf_old_produces_no_changes() -> None:
    """Old has no DWARF, new has → no DWARF changes (can't diff without old baseline)."""
    old = _snap(None)
    new = _snap(_meta(structs={"Foo": _struct("Foo", 8)}))
    result = compare(old, new)
    assert not any(c.kind == ChangeKind.STRUCT_SIZE_CHANGED for c in result.changes)


# ── struct size ───────────────────────────────────────────────────────────────

def test_struct_size_changed() -> None:
    old = _snap(_meta(structs={"Foo": _struct("Foo", 16)}))
    new = _snap(_meta(structs={"Foo": _struct("Foo", 24)}))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.STRUCT_SIZE_CHANGED in kinds
    assert result.verdict == Verdict.BREAKING


def test_struct_size_unchanged_no_change() -> None:
    s = _struct("Bar", 32)
    old = _snap(_meta(structs={"Bar": s}))
    new = _snap(_meta(structs={"Bar": s}))
    result = compare(old, new)
    assert not any(c.kind == ChangeKind.STRUCT_SIZE_CHANGED for c in result.changes)


# ── field offset ──────────────────────────────────────────────────────────────

def test_field_offset_changed() -> None:
    old_s = _struct("Foo", 16, fields=[
        _field("x", "int", offset=0, size=4),
        _field("y", "int", offset=4, size=4),
    ])
    # padding inserted before y → offset shifts
    new_s = _struct("Foo", 24, fields=[
        _field("x", "int", offset=0, size=4),
        _field("y", "int", offset=8, size=4),
    ])
    old = _snap(_meta(structs={"Foo": old_s}))
    new = _snap(_meta(structs={"Foo": new_s}))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.STRUCT_FIELD_OFFSET_CHANGED in kinds
    assert result.verdict == Verdict.BREAKING


# ── field removed ─────────────────────────────────────────────────────────────

def test_field_removed() -> None:
    old_s = _struct("Foo", 16, fields=[
        _field("x", "int", 0, 4),
        _field("secret", "int", 4, 4),
    ])
    new_s = _struct("Foo", 8, fields=[
        _field("x", "int", 0, 4),
    ])
    old = _snap(_meta(structs={"Foo": old_s}))
    new = _snap(_meta(structs={"Foo": new_s}))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.STRUCT_FIELD_REMOVED in kinds
    assert result.verdict == Verdict.BREAKING


# ── field type size changed ───────────────────────────────────────────────────

def test_field_type_size_changed() -> None:
    # int → long (size 4 → 8)
    old_s = _struct("Foo", 8, fields=[_field("n", "int", 0, 4)])
    new_s = _struct("Foo", 16, fields=[_field("n", "long", 0, 8)])
    old = _snap(_meta(structs={"Foo": old_s}))
    new = _snap(_meta(structs={"Foo": new_s}))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.STRUCT_FIELD_TYPE_CHANGED in kinds


# ── struct alignment ──────────────────────────────────────────────────────────

def test_struct_alignment_changed() -> None:
    old_s = _struct("Vec", 16, alignment=4)
    new_s = _struct("Vec", 16, alignment=8)
    old = _snap(_meta(structs={"Vec": old_s}))
    new = _snap(_meta(structs={"Vec": new_s}))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.STRUCT_ALIGNMENT_CHANGED in kinds
    assert result.verdict == Verdict.BREAKING


# ── enum underlying size ──────────────────────────────────────────────────────

def test_enum_underlying_size_changed() -> None:
    old = _snap(_meta(enums={"Color": _enum("Color", byte_size=1)}))
    new = _snap(_meta(enums={"Color": _enum("Color", byte_size=4)}))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.ENUM_UNDERLYING_SIZE_CHANGED in kinds
    assert result.verdict == Verdict.BREAKING


def test_enum_underlying_size_unchanged_no_change() -> None:
    e = _enum("Status", byte_size=4, members={"OK": 0, "ERR": 1})
    old = _snap(_meta(enums={"Status": e}))
    new = _snap(_meta(enums={"Status": e}))
    result = compare(old, new)
    assert not any(c.kind == ChangeKind.ENUM_UNDERLYING_SIZE_CHANGED for c in result.changes)


# ── enum member removed ───────────────────────────────────────────────────────

def test_enum_member_removed() -> None:
    old = _snap(_meta(enums={
        "Flags": _enum("Flags", 4, members={"A": 1, "B": 2, "C": 4})
    }))
    new = _snap(_meta(enums={
        "Flags": _enum("Flags", 4, members={"A": 1, "C": 4})  # B removed
    }))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.ENUM_MEMBER_REMOVED in kinds
    assert result.verdict == Verdict.BREAKING


# ── enum member value changed ─────────────────────────────────────────────────

def test_enum_member_value_changed() -> None:
    old = _snap(_meta(enums={"Code": _enum("Code", 4, members={"OK": 0, "FAIL": 1})}))
    new = _snap(_meta(enums={"Code": _enum("Code", 4, members={"OK": 0, "FAIL": 2})}))
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.ENUM_MEMBER_VALUE_CHANGED in kinds
    assert result.verdict == Verdict.BREAKING


# ── integration: real .so with -g ─────────────────────────────────────────────

@pytest.mark.integration
def test_parse_dwarf_real_so() -> None:
    """Compile a .so with debug info and verify DWARF layout extracted correctly."""
    src = """
    typedef struct { int x; double y; char z; } MyStruct;
    typedef enum { RED=0, GREEN=1, BLUE=2 } Color;
    int use(MyStruct *s, Color c) { return s->x + c; }
    """
    with tempfile.TemporaryDirectory() as td:
        so = Path(td) / "libtest.so"
        result = subprocess.run(
            ["gcc", "-g", "-shared", "-fPIC", "-o", str(so), "-x", "c", "-"],
            input=src.encode(), capture_output=True,
        )
        if result.returncode != 0:
            pytest.skip(f"gcc failed: {result.stderr.decode()[:200]}")

        meta = parse_dwarf_metadata(so)

    assert meta.has_dwarf
    assert "MyStruct" in meta.structs
    s = meta.structs["MyStruct"]
    assert s.byte_size == 24
    field_names = {f.name for f in s.fields}
    assert {"x", "y", "z"} <= field_names

    assert "Color" in meta.enums
    e = meta.enums["Color"]
    assert e.underlying_byte_size == 4
    assert e.members == {"RED": 0, "GREEN": 1, "BLUE": 2}


@pytest.mark.integration
def test_parse_dwarf_struct_size_regression() -> None:
    """int → long field: DWARF detects struct size change as BREAKING."""
    src_v1 = "typedef struct { int n; } Ctx; int use(Ctx *c) { return c->n; }"
    src_v2 = "typedef struct { long n; } Ctx; int use(Ctx *c) { return (int)c->n; }"

    with tempfile.TemporaryDirectory() as td:
        for src, name in [(src_v1, "v1.so"), (src_v2, "v2.so")]:
            r = subprocess.run(
                ["gcc", "-g", "-shared", "-fPIC", "-o", str(Path(td) / name), "-x", "c", "-"],
                input=src.encode(), capture_output=True,
            )
            if r.returncode != 0:
                pytest.skip(f"gcc failed: {r.stderr.decode()[:200]}")

        meta1 = parse_dwarf_metadata(Path(td) / "v1.so")
        meta2 = parse_dwarf_metadata(Path(td) / "v2.so")

    old = _snap(meta1)
    new = _snap(meta2)
    result = compare(old, new)
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.STRUCT_SIZE_CHANGED in kinds
    assert result.verdict == Verdict.BREAKING
