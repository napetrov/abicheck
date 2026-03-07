"""Serialization helpers — AbiSnapshot ↔ JSON."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Union

from .model import (
    AbiSnapshot, Function, Param, ParamKind, RecordType,
    TypeField, Variable, Visibility,
)


def snapshot_to_dict(snap: AbiSnapshot) -> dict:
    d = asdict(snap)
    # Remove private index fields
    d.pop("_func_by_mangled", None)
    d.pop("_var_by_mangled", None)
    d.pop("_type_by_name", None)
    return d


def snapshot_to_json(snap: AbiSnapshot, indent: int = 2) -> str:
    return json.dumps(snapshot_to_dict(snap), indent=indent)


def snapshot_from_dict(d: dict) -> AbiSnapshot:
    funcs = [
        Function(
            name=f["name"], mangled=f["mangled"], return_type=f["return_type"],
            params=[Param(**p) for p in f.get("params", [])],
            visibility=Visibility(f.get("visibility", "public")),
            is_virtual=f.get("is_virtual", False),
            is_noexcept=f.get("is_noexcept", False),
            vtable_index=f.get("vtable_index"),
            source_location=f.get("source_location"),
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
            fields=[TypeField(**f) for f in t.get("fields", [])],
            bases=t.get("bases", []),
            virtual_bases=t.get("virtual_bases", []),
            vtable=t.get("vtable", []),
            source_location=t.get("source_location"),
        )
        for t in d.get("types", [])
    ]
    return AbiSnapshot(
        library=d["library"], version=d["version"],
        functions=funcs, variables=variables, types=types,
    )


def load_snapshot(path: Union[str, Path]) -> AbiSnapshot:
    with open(path, encoding="utf-8") as f:
        return snapshot_from_dict(json.load(f))


def save_snapshot(snap: AbiSnapshot, path: Union[str, Path]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(snapshot_to_json(snap))
