# Copyright 2026 Nikolay Petrov
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""PDB-based debug info extraction for Windows PE binaries.

Produces the **same** ``DwarfMetadata`` and ``AdvancedDwarfMetadata`` dataclasses
used by the DWARF pipeline so that the checker's ``_diff_dwarf()`` and
``_diff_advanced_dwarf()`` detectors work without modification.

Phases implemented:
  1. Struct/class/union sizes and field layouts (offsets, types) from TPI stream
  2. Enum underlying types and member values from TPI stream
  3. Calling convention extraction from LF_PROCEDURE / LF_MFUNCTION
  4. Toolchain info from DBI stream header (machine type, build number)

Public API
----------
parse_pdb_debug_info(pdb_path)
    → tuple[DwarfMetadata, AdvancedDwarfMetadata]

Requires a PDB file path.  Use ``pdb_utils.locate_pdb()`` to find the PDB
for a given PE binary.
"""
from __future__ import annotations

import logging
import re
import struct
from pathlib import Path

from .dwarf_advanced import AdvancedDwarfMetadata, ToolchainInfo
from .dwarf_metadata import DwarfMetadata, EnumInfo, FieldInfo, StructLayout
from .pdb_parser import (
    CvEnumerator,
    CvMember,
    CvStruct,
    PdbFile,
    TypeDatabase,
    parse_pdb,
)

log = logging.getLogger(__name__)

# Machine type values from PE/COFF spec (DBI header.machine field)
_MACHINE_NAMES: dict[int, str] = {
    0x014C: "x86",
    0x0200: "IA64",
    0x8664: "AMD64",
    0xAA64: "ARM64",
    0x01C0: "ARM",
    0x01C4: "ARMNT",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_pdb_debug_info(
    pdb_path: Path,
) -> tuple[DwarfMetadata, AdvancedDwarfMetadata]:
    """Parse a PDB file and return (DwarfMetadata, AdvancedDwarfMetadata).

    Returns ``(DwarfMetadata(), AdvancedDwarfMetadata())`` on any error.
    Never raises.
    """
    empty = DwarfMetadata(), AdvancedDwarfMetadata()

    try:
        pdb = parse_pdb(pdb_path)
    except (ValueError, OSError, struct.error) as exc:
        log.warning("parse_pdb_debug_info: failed to parse %s: %s", pdb_path, exc)
        return empty

    if pdb.types is None:
        log.debug("parse_pdb_debug_info: no TPI stream in %s", pdb_path)
        return empty

    meta = DwarfMetadata(has_dwarf=True)
    adv = AdvancedDwarfMetadata(has_dwarf=True)

    try:
        _extract_struct_layouts(pdb.types, meta)
    except Exception as exc:  # noqa: BLE001
        log.warning("parse_pdb_debug_info: struct extraction failed: %s", exc)

    try:
        _extract_enums(pdb.types, meta)
    except Exception as exc:  # noqa: BLE001
        log.warning("parse_pdb_debug_info: enum extraction failed: %s", exc)

    try:
        _extract_calling_conventions(pdb.types, adv)
    except Exception as exc:  # noqa: BLE001
        log.warning("parse_pdb_debug_info: calling convention extraction failed: %s", exc)

    try:
        _extract_toolchain_info(pdb, adv)
    except Exception as exc:  # noqa: BLE001
        log.warning("parse_pdb_debug_info: toolchain info extraction failed: %s", exc)

    return meta, adv


# ---------------------------------------------------------------------------
# Phase 1: Struct/class/union layouts
# ---------------------------------------------------------------------------

def _extract_struct_layouts(types: TypeDatabase, meta: DwarfMetadata) -> None:
    """Extract struct/class/union layouts from TPI into DwarfMetadata.structs."""
    for ti, cv_struct in types.all_structs().items():
        if cv_struct.is_forward_ref:
            continue
        if not cv_struct.name:
            continue
        # Skip anonymous/unnamed types and compiler-internal names
        if cv_struct.name.startswith("<") or cv_struct.name.startswith("__"):
            continue

        fields = _extract_fields(types, cv_struct)

        layout = StructLayout(
            name=cv_struct.name,
            byte_size=cv_struct.byte_size,
            alignment=0,  # PDB doesn't store explicit alignment
            fields=fields,
            is_union=cv_struct.is_union,
        )

        # Track packed structs for advanced metadata
        if cv_struct.is_packed:
            # Will be picked up later in _extract_calling_conventions
            pass

        # ODR: keep first complete definition
        if cv_struct.name not in meta.structs:
            meta.structs[cv_struct.name] = layout


def _extract_fields(types: TypeDatabase, cv_struct: CvStruct) -> list[FieldInfo]:
    """Extract field information from a struct's fieldlist."""
    if cv_struct.field_list_ti == 0:
        return []

    members = types.get_fieldlist(cv_struct.field_list_ti)
    fields: list[FieldInfo] = []

    for member in members:
        if not isinstance(member, CvMember):
            continue
        if not member.name:
            continue

        type_name = types.type_name(member.type_ti)
        byte_size = types.type_size(member.type_ti)
        bit_offset = 0
        bit_size = 0

        # Check if the member type is a bitfield
        bf = types._bitfields.get(member.type_ti)
        if bf is not None:
            bit_size = bf.length
            bit_offset = bf.position
            # For bitfields, resolve the underlying type name and size
            type_name = types.type_name(bf.underlying_ti)
            byte_size = types.type_size(bf.underlying_ti)

        fields.append(FieldInfo(
            name=member.name,
            type_name=type_name,
            byte_offset=member.offset,
            byte_size=byte_size,
            bit_offset=bit_offset,
            bit_size=bit_size,
        ))

    return fields


# ---------------------------------------------------------------------------
# Phase 2: Enum types
# ---------------------------------------------------------------------------

def _extract_enums(types: TypeDatabase, meta: DwarfMetadata) -> None:
    """Extract enum types from TPI into DwarfMetadata.enums."""
    for ti, cv_enum in types.all_enums().items():
        if cv_enum.is_forward_ref:
            continue
        if not cv_enum.name:
            continue
        if cv_enum.name.startswith("<") or cv_enum.name.startswith("__"):
            continue

        underlying_size = types.type_size(cv_enum.underlying_type_ti)

        members: dict[str, int] = {}
        field_members = types.get_fieldlist(cv_enum.field_list_ti)
        for m in field_members:
            if isinstance(m, CvEnumerator) and m.name:
                members[m.name] = m.value

        enum_info = EnumInfo(
            name=cv_enum.name,
            underlying_byte_size=underlying_size,
            members=members,
        )

        if cv_enum.name not in meta.enums:
            meta.enums[cv_enum.name] = enum_info


# ---------------------------------------------------------------------------
# Phase 3: Calling conventions
# ---------------------------------------------------------------------------

def _extract_calling_conventions(
    types: TypeDatabase, adv: AdvancedDwarfMetadata,
) -> None:
    """Extract calling conventions from LF_PROCEDURE and LF_MFUNCTION.

    Populates ``adv.packed_structs``.

    Note: ``adv.calling_conventions`` is NOT populated because TPI type
    indices are not stable across builds — unrelated type insertions shift
    all indices.  ``diff_advanced_dwarf()`` compares calling conventions by
    key intersection, so using TPI indices as keys would cause false
    ``calling_convention_changed`` reports.  Populating this dict requires
    stable function identities (linkage names) from the PDB symbol stream,
    which is not yet implemented.
    """
    # Collect packed structs
    for ti, cv_struct in types.all_structs().items():
        if cv_struct.is_forward_ref:
            continue
        if cv_struct.name:
            adv.all_struct_names.add(cv_struct.name)
            if cv_struct.is_packed:
                adv.packed_structs.add(cv_struct.name)


# ---------------------------------------------------------------------------
# Phase 4: Toolchain / compiler info from DBI
# ---------------------------------------------------------------------------

def _extract_toolchain_info(pdb: PdbFile, adv: AdvancedDwarfMetadata) -> None:
    """Extract compiler/toolchain info from DBI stream header."""
    if pdb.dbi is None:
        return

    h = pdb.dbi.header
    machine = _MACHINE_NAMES.get(h.machine, f"0x{h.machine:04x}")

    # BuildNumber: bits 0-7 = minor, bits 8-14 = major, bit 15 = new format
    major = (h.build_number >> 8) & 0x7F
    minor = h.build_number & 0xFF
    # Construct a producer-like string from DBI metadata
    producer = f"MSVC {major}.{minor}"
    if machine:
        producer += f" ({machine})"

    abi_flags: set[str] = set()
    # Machine type implies ABI
    if h.machine == 0x014C:
        abi_flags.add("-m32")
    elif h.machine == 0x8664:
        abi_flags.add("-m64")
    elif h.machine == 0xAA64:
        abi_flags.add("-marm64")

    # Check for incremental linking
    if h.flags & 0x01:
        abi_flags.add("/INCREMENTAL")

    adv.toolchain = ToolchainInfo(
        producer_string=producer,
        compiler="MSVC",
        version=f"{major}.{minor}",
        abi_flags=abi_flags,
    )

    # Try to extract more detailed info from module names
    for mod in pdb.dbi.modules:
        obj = mod.obj_file_name
        if not obj:
            continue
        # Look for MSVC version patterns in obj paths
        # e.g. "C:\Program Files\...\VC\Tools\MSVC\14.36.32532\..."
        m = re.search(r"MSVC[\\/](\d+\.\d+\.\d+)", obj)
        if m:
            adv.toolchain.version = m.group(1)
            adv.toolchain.producer_string = f"MSVC {m.group(1)} ({machine})"
            break
