"""Serialization helpers — AbiSnapshot ↔ JSON."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .model import (
    AbiSnapshot,
    EnumMember,
    EnumType,
    Function,
    Param,
    RecordType,
    TypeField,
    Variable,
    Visibility,
)


def snapshot_to_dict(snap: AbiSnapshot) -> dict[str, Any]:
    # Reset cache fields to None before asdict() to prevent double-serialization.
    # asdict() would otherwise recursively serialize the index dicts (containing
    # Function/Variable objects), bloating the output and corrupting roundtrip.
    snap._func_by_mangled = None
    snap._var_by_mangled = None
    snap._type_by_name = None
    d = asdict(snap)
    d.pop("_func_by_mangled", None)
    d.pop("_var_by_mangled", None)
    d.pop("_type_by_name", None)
    return d


def _enum_type_from_dict(e: dict[str, Any]) -> EnumType:
    return EnumType(
        name=e["name"],
        members=[EnumMember(name=m["name"], value=m["value"]) for m in e.get("members", [])],
        underlying_type=e.get("underlying_type", "int"),
    )


def snapshot_to_json(snap: AbiSnapshot, indent: int = 2) -> str:
    return json.dumps(snapshot_to_dict(snap), indent=indent)


def snapshot_from_dict(d: dict[str, Any]) -> AbiSnapshot:
    funcs = [
        Function(
            name=f["name"], mangled=f["mangled"], return_type=f["return_type"],
            params=[Param(**p) for p in f.get("params", [])],
            visibility=Visibility(f.get("visibility", "public")),
            is_virtual=f.get("is_virtual", False),
            is_noexcept=f.get("is_noexcept", False),
            vtable_index=f.get("vtable_index"),
            source_location=f.get("source_location"),
            is_static=f.get("is_static", False),
            is_const=f.get("is_const", False),
            is_volatile=f.get("is_volatile", False),
            is_pure_virtual=f.get("is_pure_virtual", False),
        )
        for f in d.get("functions", [])
    ]
    variables = [
        Variable(
            name=v["name"], mangled=v["mangled"], type=v["type"],
            visibility=Visibility(v.get("visibility", "public")),
            source_location=v.get("source_location"),
        )
        for v in d.get("variables", [])
    ]
    types = [
        RecordType(
            name=t["name"], kind=t["kind"],
            size_bits=t.get("size_bits"),
            fields=[
                TypeField(
                    name=f["name"], type=f["type"],
                    offset_bits=f.get("offset_bits"),
                    is_bitfield=f.get("is_bitfield", False),
                    bitfield_bits=f.get("bitfield_bits"),
                )
                for f in t.get("fields", [])
            ],
            bases=t.get("bases", []),
            virtual_bases=t.get("virtual_bases", []),
            vtable=t.get("vtable", []),
            source_location=t.get("source_location"),
            is_union=t.get("is_union", False),
        )
        for t in d.get("types", [])
    ]
    enums = [_enum_type_from_dict(e) for e in d.get("enums", [])]
    typedefs: dict[str, str] = d.get("typedefs", {})
    return AbiSnapshot(
        library=d["library"], version=d["version"],
        functions=funcs, variables=variables, types=types,
        enums=enums, typedefs=typedefs,
    )


def load_snapshot(path: str | Path) -> AbiSnapshot:
    with open(path, encoding="utf-8") as f:
        return snapshot_from_dict(json.load(f))


def save_snapshot(snap: AbiSnapshot, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(snapshot_to_json(snap))
