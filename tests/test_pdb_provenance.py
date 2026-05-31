# SPDX-License-Identifier: Apache-2.0
# Copyright The abicheck Authors.
"""PDB declaration-provenance extraction (ADR-024 Phase 1).

Exercises the source-file (``decl_file``) plumbing end to end at the layers
that are testable on Linux without MSVC: the IPI ``LF_UDT_SRC_LINE`` parser,
the ``DwarfMetadata`` ``decl_file`` field, and the ``DwarfMetadata`` → model
type bridge that lets PDB-derived types reach public-surface resolution.
"""
from __future__ import annotations

import struct

from abicheck.dwarf_metadata import DwarfMetadata, EnumInfo, FieldInfo, StructLayout
from abicheck.model import ScopeOrigin
from abicheck.pdb_model import model_types_from_dwarf_metadata
from abicheck.pdb_parser import (
    LF_STRING_ID,
    LF_UDT_MOD_SRC_LINE,
    LF_UDT_SRC_LINE,
    extract_udt_source_files,
    parse_tpi_stream,
)
from abicheck.provenance import apply_provenance


def _build_ipi_stream(records: list[tuple[int, bytes]]) -> bytes:
    """Build an IPI stream (identical record layout to TPI)."""
    ti_begin = 0x1000
    ti_end = ti_begin + len(records)
    rec_data = b""
    for leaf, payload in records:
        rec_len = 2 + len(payload)
        rec_bytes = struct.pack("<HH", rec_len, leaf) + payload
        pad = (4 - (len(rec_bytes) % 4)) % 4
        rec_bytes += b"\x00" * pad
        rec_data += rec_bytes
    header = struct.pack(
        "<IIIII", 20040203, 56, ti_begin, ti_end, len(rec_data)
    )
    header += b"\x00" * (56 - len(header))
    return header + rec_data


def _string_id(name: str) -> bytes:
    # { substr_list_id: u32, name: char[] }
    return struct.pack("<I", 0) + name.encode() + b"\x00"


def _udt_src_line(udt_ti: int, src_id: int, line: int) -> bytes:
    return struct.pack("<III", udt_ti, src_id, line)


def _udt_mod_src_line(udt_ti: int, src_id: int, line: int, mod: int) -> bytes:
    return struct.pack("<IIIH", udt_ti, src_id, line, mod)


class TestExtractUdtSourceFiles:
    def test_resolves_src_line_via_string_id(self) -> None:
        # IPI: ti 0x1000 = LF_STRING_ID("api.h"); ti 0x1001 ties UDT 0x2000 → it.
        ipi = parse_tpi_stream(
            _build_ipi_stream(
                [
                    (LF_STRING_ID, _string_id("api.h")),
                    (LF_UDT_SRC_LINE, _udt_src_line(0x2000, 0x1000, 42)),
                ]
            )
        )
        assert extract_udt_source_files(ipi) == {0x2000: "api.h"}

    def test_mod_src_line_also_resolved(self) -> None:
        ipi = parse_tpi_stream(
            _build_ipi_stream(
                [
                    (LF_STRING_ID, _string_id("detail/private.h")),
                    (LF_UDT_MOD_SRC_LINE, _udt_mod_src_line(0x2001, 0x1000, 7, 3)),
                ]
            )
        )
        assert extract_udt_source_files(ipi) == {0x2001: "detail/private.h"}

    def test_unresolvable_string_id_skipped(self) -> None:
        # src id 0x1999 has no LF_STRING_ID record → entry dropped, not crash.
        ipi = parse_tpi_stream(
            _build_ipi_stream(
                [(LF_UDT_SRC_LINE, _udt_src_line(0x2000, 0x1999, 1))]
            )
        )
        assert extract_udt_source_files(ipi) == {}

    def test_first_definition_wins(self) -> None:
        ipi = parse_tpi_stream(
            _build_ipi_stream(
                [
                    (LF_STRING_ID, _string_id("first.h")),
                    (LF_STRING_ID, _string_id("second.h")),
                    (LF_UDT_SRC_LINE, _udt_src_line(0x2000, 0x1000, 1)),
                    (LF_UDT_SRC_LINE, _udt_src_line(0x2000, 0x1001, 2)),
                ]
            )
        )
        assert extract_udt_source_files(ipi) == {0x2000: "first.h"}


class TestDwarfMetadataDeclFile:
    def test_struct_layout_carries_decl_file(self) -> None:
        layout = StructLayout(name="Vec3", byte_size=12, decl_file="include/api.h")
        assert layout.decl_file == "include/api.h"

    def test_decl_file_defaults_none(self) -> None:
        assert StructLayout(name="X", byte_size=4).decl_file is None
        assert EnumInfo(name="E", underlying_byte_size=4).decl_file is None


class TestModelBridge:
    def test_record_source_location_from_decl_file(self) -> None:
        meta = DwarfMetadata(has_dwarf=True)
        meta.structs["Vec3"] = StructLayout(
            name="Vec3",
            byte_size=12,
            fields=[FieldInfo(name="x", type_name="float", byte_offset=0, byte_size=4)],
            decl_file="include/api.h",
        )
        meta.enums["Color"] = EnumInfo(
            name="Color",
            underlying_byte_size=4,
            members={"RED": 0, "GREEN": 1},
            decl_file="include/api.h",
        )
        records, enums = model_types_from_dwarf_metadata(meta)
        assert len(records) == 1 and len(enums) == 1
        assert records[0].name == "Vec3"
        assert records[0].source_location == "include/api.h"
        assert records[0].size_bits == 96
        assert records[0].fields[0].offset_bits == 0
        assert enums[0].source_location == "include/api.h"
        assert enums[0].underlying_type == "int"

    def test_empty_metadata_yields_nothing(self) -> None:
        assert model_types_from_dwarf_metadata(None) == ([], [])
        assert model_types_from_dwarf_metadata(DwarfMetadata()) == ([], [])

    def test_bridge_feeds_provenance_classification(self) -> None:
        # The decl_file → source_location bridge lets apply_provenance classify
        # a PDB-derived type's ScopeOrigin against a public-header set — the
        # whole point of PDB provenance (ADR-024 Phase 1) on the PE path.
        from abicheck.model import AbiSnapshot

        meta = DwarfMetadata(has_dwarf=True)
        meta.structs["PublicType"] = StructLayout(
            name="PublicType", byte_size=8, decl_file="include/api.h"
        )
        meta.structs["PrivateType"] = StructLayout(
            name="PrivateType", byte_size=8, decl_file="src/internal.h"
        )
        records, enums = model_types_from_dwarf_metadata(meta)
        snap = AbiSnapshot(library="lib.dll", version="1", types=records, enums=enums)
        apply_provenance(snap, public_headers=["include/api.h"], public_header_dirs=None)
        by_name = {t.name: t for t in snap.types}
        assert by_name["PublicType"].origin == ScopeOrigin.PUBLIC_HEADER
        assert by_name["PrivateType"].origin == ScopeOrigin.PRIVATE_HEADER
