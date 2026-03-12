"""Minimal ABICC (abi-dumper) Perl dump importer.

This module is intentionally isolated from main compat logic so ABICC dump parsing
can evolve independently while keeping the CLI flow simple.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .model import AbiSnapshot, Function, Param, RecordType, Variable, Visibility


def looks_like_perl_dump(text: str) -> bool:
    """Heuristic detection for Data::Dumper ABI dumps."""
    head = text.lstrip()
    return head.startswith("$VAR1")


def import_abicc_perl_dump(path: Path) -> AbiSnapshot:
    """Convert abi-dumper Perl Data::Dumper output into a minimal AbiSnapshot.

    This importer is deliberately lenient and migration-focused:
    - parses symbols and a minimal subset of type names,
    - tolerates unknown sections,
    - preserves compatibility verdict signal over full-fidelity metadata.
    """
    if shutil.which("perl") is None:
        raise ValueError(
            "ABICC Perl dump detected, but Perl is not available in PATH. "
            "Install Perl or pre-convert the dump to abicheck JSON."
        )

    perl_code = (
        "use JSON::PP qw(encode_json); "
        "local $/; "
        "my $txt=<>; "
        "my $VAR1; "
        "my $res = eval $txt; "
        "die $@ if $@; "
        "my $obj = defined($VAR1) ? $VAR1 : $res; "
        "print encode_json($obj);"
    )
    proc = subprocess.run(
        ["perl", "-MJSON::PP", "-e", perl_code, str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise ValueError(f"Failed to parse ABICC Perl dump: {stderr or 'unknown parse error'}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode converted ABICC dump JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Invalid ABICC Perl dump: top-level structure is not a hash/dict")

    return _snapshot_from_abicc_dict(data, path)


def _snapshot_from_abicc_dict(data: dict[str, object], path: Path) -> AbiSnapshot:
    type_info = data.get("TypeInfo")
    symbol_info = data.get("SymbolInfo")

    type_map: dict[str, dict[str, object]] = type_info if isinstance(type_info, dict) else {}
    sym_map: dict[str, dict[str, object]] = symbol_info if isinstance(symbol_info, dict) else {}

    library = str(data.get("LibraryName") or path.stem)
    version = str(data.get("LibraryVersion") or "unknown")

    functions: list[Function] = []
    variables: list[Variable] = []

    for _, sym in sym_map.items():
        if not isinstance(sym, dict):
            continue

        mangled = str(sym.get("MnglName") or "")
        if not mangled:
            continue

        short_name = str(sym.get("ShortName") or mangled)

        is_function = any(k in sym for k in ("Param", "Return", "Constructor", "Destructor"))
        if is_function:
            params = _parse_params(sym, type_map)
            return_type = _resolve_type_name(sym.get("Return"), type_map)
            functions.append(
                Function(
                    name=short_name,
                    mangled=mangled,
                    return_type=return_type,
                    params=params,
                    visibility=Visibility.PUBLIC,
                )
            )
        else:
            var_type = _resolve_type_name(sym.get("Type"), type_map)
            variables.append(
                Variable(
                    name=short_name,
                    mangled=mangled,
                    type=var_type,
                    visibility=Visibility.PUBLIC,
                )
            )

    types = _extract_record_types(type_map)

    return AbiSnapshot(
        library=library,
        version=version,
        functions=functions,
        variables=variables,
        types=types,
    )


def _parse_params(sym: dict[str, object], type_map: dict[str, dict[str, object]]) -> list[Param]:
    raw = sym.get("Param")
    if not isinstance(raw, dict):
        return []

    params: list[tuple[int, Param]] = []
    for pos, pinfo in raw.items():
        if not isinstance(pinfo, dict):
            continue
        try:
            idx = int(str(pos))
        except ValueError:
            idx = 9999

        ptype = _resolve_type_name(pinfo.get("type"), type_map)
        pname = str(pinfo.get("name") or f"arg{idx}")
        params.append((idx, Param(name=pname, type=ptype)))

    params.sort(key=lambda x: x[0])
    return [p for _, p in params]


def _resolve_type_name(type_id: object, type_map: dict[str, dict[str, object]]) -> str:
    if type_id is None:
        return "unknown"

    tid = str(type_id)
    tinfo = type_map.get(tid)
    if not isinstance(tinfo, dict):
        return "unknown"

    name = tinfo.get("Name")
    if isinstance(name, str) and name.strip():
        return name

    return "unknown"


def _extract_record_types(type_map: dict[str, dict[str, object]]) -> list[RecordType]:
    out: list[RecordType] = []
    for _, tinfo in type_map.items():
        if not isinstance(tinfo, dict):
            continue
        kind_raw = str(tinfo.get("Type") or "").lower()
        if kind_raw not in ("struct", "class", "union"):
            continue

        name = tinfo.get("Name")
        if not isinstance(name, str) or not name.strip():
            continue

        out.append(
            RecordType(
                name=name,
                kind=kind_raw,
                is_union=(kind_raw == "union"),
            )
        )
    return out
