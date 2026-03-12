"""Serialization helpers — AbiSnapshot ↔ JSON."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .model import (
    AbiSnapshot,
    AccessLevel,
    EnumMember,
    EnumType,
    Function,
    Param,
    ParamKind,
    RecordType,
    TypeField,
    Variable,
    Visibility,
)

# Current schema version for snapshot serialization.
# Increment this whenever the snapshot format changes in a backward-incompatible way.
# v1: initial format (pre-schema-versioning; snapshots without schema_version are treated as v1)
# v2: schema_version field added (PR #89)
SCHEMA_VERSION: int = 2


def _sets_to_lists(obj: Any) -> Any:
    """Recursively convert any set to a sorted list for JSON serialization.

    dataclasses.asdict() does NOT convert set → list, so json.dumps() would
    raise TypeError. This post-processes the entire dict tree.
    """
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, dict):
        return {k: _sets_to_lists(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sets_to_lists(v) for v in obj]
    return obj


def snapshot_to_dict(snap: AbiSnapshot) -> dict[str, Any]:
    # Reset cache fields to None before asdict() to prevent double-serialization.
    snap._func_by_mangled = None
    snap._var_by_mangled = None
    snap._type_by_name = None
    d = asdict(snap)
    d.pop("_func_by_mangled", None)
    d.pop("_var_by_mangled", None)
    d.pop("_type_by_name", None)

    # Serialize ElfMetadata enums to strings for JSON compatibility
    if d.get("elf"):
        elf = d["elf"]
        for sym in elf.get("symbols", []):
            sym["binding"] = sym["binding"] if isinstance(sym["binding"], str) else sym["binding"].value
            sym["sym_type"] = sym["sym_type"] if isinstance(sym["sym_type"], str) else sym["sym_type"].value

    # Convert all sets → sorted lists (needed for AdvancedDwarfMetadata.packed_structs
    # and ToolchainInfo.abi_flags; json.dumps raises TypeError on set objects)
    converted: dict[str, Any] = _sets_to_lists(d)

    # Embed schema version for forward-compatibility.
    # Placed at top level so loaders can inspect it without parsing the full snapshot.
    converted["schema_version"] = SCHEMA_VERSION

    return converted


def _enum_type_from_dict(e: dict[str, Any]) -> EnumType:
    return EnumType(
        name=e["name"],
        members=[EnumMember(name=m["name"], value=m["value"]) for m in e.get("members", [])],
        underlying_type=e.get("underlying_type", "int"),
    )


def snapshot_to_json(snap: AbiSnapshot, indent: int = 2) -> str:
    return json.dumps(snapshot_to_dict(snap), indent=indent)


def _elf_from_dict(e: dict[str, Any]) -> Any:
    from .elf_metadata import ElfMetadata, ElfSymbol, SymbolBinding, SymbolType
    syms = [
        ElfSymbol(
            name=s["name"],
            binding=SymbolBinding(s.get("binding", "global")),
            sym_type=SymbolType(s.get("sym_type", "func")),
            size=s.get("size", 0),
            version=s.get("version", ""),
            is_default=s.get("is_default", True),
            visibility=s.get("visibility", "default"),
        )
        for s in e.get("symbols", [])
    ]
    return ElfMetadata(
        soname=e.get("soname", ""),
        needed=e.get("needed", []),
        rpath=e.get("rpath", ""),
        runpath=e.get("runpath", ""),
        versions_defined=e.get("versions_defined", []),
        versions_required=e.get("versions_required", {}),
        symbols=syms,
    )


def _dwarf_from_dict(d: dict[str, Any]) -> Any:
    from .dwarf_metadata import DwarfMetadata, EnumInfo, FieldInfo, StructLayout

    structs = {
        name: StructLayout(
            name=s.get("name", name),
            byte_size=s.get("byte_size", 0),
            alignment=s.get("alignment", 0),
            fields=[
                FieldInfo(
                    name=f.get("name", ""),
                    type_name=f.get("type_name", "unknown"),
                    byte_offset=f.get("byte_offset", 0),
                    byte_size=f.get("byte_size", 0),
                    bit_offset=f.get("bit_offset", 0),
                    bit_size=f.get("bit_size", 0),
                )
                for f in s.get("fields", [])
            ],
            is_union=s.get("is_union", False),
        )
        for name, s in d.get("structs", {}).items()
    }

    enums = {
        name: EnumInfo(
            name=e.get("name", name),
            underlying_byte_size=e.get("underlying_byte_size", 0),
            members=e.get("members", {}),
        )
        for name, e in d.get("enums", {}).items()
    }

    return DwarfMetadata(
        structs=structs,
        enums=enums,
        has_dwarf=d.get("has_dwarf", False),
    )


def _dwarf_advanced_from_dict(d: dict[str, Any]) -> Any:
    from .dwarf_advanced import AdvancedDwarfMetadata, ToolchainInfo

    tc = d.get("toolchain", {})
    toolchain = ToolchainInfo(
        producer_string=tc.get("producer_string", ""),
        compiler=tc.get("compiler", ""),
        version=tc.get("version", ""),
        abi_flags=set(tc.get("abi_flags", [])),
    )
    return AdvancedDwarfMetadata(
        has_dwarf=d.get("has_dwarf", False),
        toolchain=toolchain,
        calling_conventions=d.get("calling_conventions", {}),
        value_abi_traits=d.get("value_abi_traits", {}),
        packed_structs=set(d.get("packed_structs", [])),
        all_struct_names=set(d.get("all_struct_names", [])),
    )


def snapshot_from_dict(d: dict[str, Any]) -> AbiSnapshot:
    # Inspect schema version for future migration hooks.
    # Snapshots without schema_version are treated as v1 (pre-versioning format).
    # Currently only v1 and v2 exist and have the same on-disk layout, so no
    # migration is required.  This baseline lets future PRs add migration logic here.
    _schema_version: int = int(d.get("schema_version", 1))  # noqa: F841 — used by future migration
    funcs = [
        Function(
            name=f["name"], mangled=f["mangled"], return_type=f["return_type"],
            params=[
                Param(
                    name=p.get("name", ""), type=p.get("type", ""),
                    kind=ParamKind(p.get("kind", "value")),
                    default=p.get("default", None),
                    pointer_depth=p.get("pointer_depth", 0),
                    is_restrict=p.get("is_restrict", False),
                    is_va_list=p.get("is_va_list", False),
                )
                for p in f.get("params", [])
            ],
            visibility=Visibility(f.get("visibility", "public")),
            is_virtual=f.get("is_virtual", False),
            is_noexcept=f.get("is_noexcept", False),
            vtable_index=f.get("vtable_index"),
            source_location=f.get("source_location"),
            is_static=f.get("is_static", False),
            is_const=f.get("is_const", False),
            is_volatile=f.get("is_volatile", False),
            is_pure_virtual=f.get("is_pure_virtual", False),
            is_deleted=f.get("is_deleted", False),
            is_inline=f.get("is_inline", False),
            is_extern_c=f.get("is_extern_c", False),
            access=AccessLevel(f.get("access", "public")),
            return_pointer_depth=f.get("return_pointer_depth", 0),
        )
        for f in d.get("functions", [])
    ]
    variables = [
        Variable(
            name=v["name"], mangled=v["mangled"], type=v["type"],
            visibility=Visibility(v.get("visibility", "public")),
            source_location=v.get("source_location"),
            is_const=v.get("is_const", False),
            value=v.get("value"),
            access=AccessLevel(v.get("access", "public")),
        )
        for v in d.get("variables", [])
    ]
    types = [
        RecordType(
            name=t["name"], kind=t["kind"],
            size_bits=t.get("size_bits"),
            alignment_bits=t.get("alignment_bits"),
            fields=[
                TypeField(
                    name=f["name"], type=f["type"],
                    offset_bits=f.get("offset_bits"),
                    is_bitfield=f.get("is_bitfield", False),
                    bitfield_bits=f.get("bitfield_bits"),
                    is_const=f.get("is_const", False),
                    is_volatile=f.get("is_volatile", False),
                    is_mutable=f.get("is_mutable", False),
                    access=AccessLevel(f.get("access", "public")),
                )
                for f in t.get("fields", [])
            ],
            bases=t.get("bases", []),
            virtual_bases=t.get("virtual_bases", []),
            vtable=t.get("vtable", []),
            source_location=t.get("source_location"),
            is_union=t.get("is_union", t.get("kind") == "union"),
        )
        for t in d.get("types", [])
    ]
    enums = [_enum_type_from_dict(e) for e in d.get("enums", [])]
    typedefs: dict[str, str] = d.get("typedefs", {})
    elf_data = d.get("elf")
    dwarf_data = d.get("dwarf")
    dwarf_adv_data = d.get("dwarf_advanced")

    elf = _elf_from_dict(elf_data) if isinstance(elf_data, dict) else None
    dwarf = _dwarf_from_dict(dwarf_data) if isinstance(dwarf_data, dict) else None
    dwarf_advanced = (
        _dwarf_advanced_from_dict(dwarf_adv_data)
        if isinstance(dwarf_adv_data, dict)
        else None
    )

    return AbiSnapshot(
        library=d["library"], version=d["version"],
        functions=funcs, variables=variables, types=types,
        enums=enums, typedefs=typedefs,
        elf=elf, dwarf=dwarf, dwarf_advanced=dwarf_advanced,
        elf_only_mode=bool(d.get("elf_only_mode", False)),
        constants=d.get("constants", {}),
        platform=d.get("platform"),
        language_profile=d.get("language_profile"),
    )


def load_snapshot(path: str | Path) -> AbiSnapshot:
    with open(path, encoding="utf-8") as f:
        return snapshot_from_dict(json.load(f))


def save_snapshot(snap: AbiSnapshot, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(snapshot_to_json(snap))
