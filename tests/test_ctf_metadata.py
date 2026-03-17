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

"""Tests for CTF (Compact C Type Format) parser."""
from __future__ import annotations

import struct
import zlib

import pytest

from abicheck.ctf_metadata import (
    CTF_F_COMPRESS,
    CTF_K_CONST,
    CTF_K_ENUM,
    CTF_K_INTEGER,
    CTF_K_POINTER,
    CTF_K_STRUCT,
    CTF_K_TYPEDEF,
    CTF_K_UNION,
    CTF_MAGIC,
    CTF_VERSION_3,
    CtfMetadata,
    _parse_header,
    _read_string,
    parse_ctf_from_bytes,
)


# ---------------------------------------------------------------------------
# Helpers to build synthetic CTF v3 blobs
# ---------------------------------------------------------------------------

class CtfBuilder:
    """Helper to construct synthetic CTF v3 binary blobs for testing."""

    def __init__(self) -> None:
        self._strings = bytearray(b"\x00")  # string section starts with NUL
        self._type_entries: list[bytes] = []
        self._str_offsets: dict[str, int] = {"": 0}

    def add_string(self, s: str) -> int:
        if s in self._str_offsets:
            return self._str_offsets[s]
        off = len(self._strings)
        self._strings.extend(s.encode("utf-8") + b"\x00")
        self._str_offsets[s] = off
        return off

    def add_type(self, name: str, kind: int, vlen: int, size_or_type: int,
                 extra: bytes = b"", isroot: bool = False) -> int:
        """Add a CTF v3 type entry, return its 1-based type ID."""
        name_off = self.add_string(name) if name else 0
        # v3 info: isroot(1) + kind(5) in upper byte, vlen(16) in lower
        info = (int(isroot) << 31) | (kind << 24) | (vlen & 0xFFFF)
        entry = struct.pack("<III", name_off, info, size_or_type) + extra
        self._type_entries.append(entry)
        return len(self._type_entries)  # 1-based

    def build(self, *, compress: bool = False) -> bytes:
        """Build a complete CTF v3 blob."""
        type_data = b"".join(self._type_entries)
        str_data = bytes(self._strings)
        hdr_size = 36
        # Offsets are relative to the end of the header
        label_off = 0
        object_off = 0
        func_off = 0
        type_off = 0
        str_off = len(type_data)
        str_len = len(str_data)

        flags = CTF_F_COMPRESS if compress else 0

        header = struct.pack("<HBB", CTF_MAGIC, CTF_VERSION_3, flags)
        header += struct.pack("<IIIIIIII",
                              0,  # parent_label
                              0,  # parent_name
                              label_off,
                              object_off,
                              func_off,
                              type_off,
                              str_off,
                              str_len)

        body = type_data + str_data

        if compress:
            # Compress everything after the preamble (4 bytes)
            preamble = header[:4]
            rest = header[4:] + body
            compressed = zlib.compress(rest)
            return preamble + compressed
        else:
            return header + body


# ---------------------------------------------------------------------------
# String table
# ---------------------------------------------------------------------------

class TestReadString:
    def test_basic(self) -> None:
        data = b"hello\x00world\x00"
        assert _read_string(data, 0) == "hello"
        assert _read_string(data, 6) == "world"

    def test_empty(self) -> None:
        assert _read_string(b"\x00", 0) == ""

    def test_out_of_bounds(self) -> None:
        assert _read_string(b"abc\x00", 100) == ""


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

class TestParseHeader:
    def test_valid_header(self) -> None:
        b = CtfBuilder()
        data = b.build()
        hdr = _parse_header(data)
        assert hdr.magic == CTF_MAGIC
        assert hdr.version == CTF_VERSION_3

    def test_bad_magic(self) -> None:
        data = struct.pack("<HBB", 0xDEAD, 3, 0) + b"\x00" * 40
        with pytest.raises(ValueError, match="Bad CTF magic"):
            _parse_header(data)

    def test_too_small(self) -> None:
        with pytest.raises(ValueError, match="too small"):
            _parse_header(b"\x00")


# ---------------------------------------------------------------------------
# Full parse: structs
# ---------------------------------------------------------------------------

class TestCtfStructs:
    def test_simple_struct(self) -> None:
        b = CtfBuilder()
        # Add INT type (id=1): encoding word = nr_bits in lower 16 bits
        int_enc = struct.pack("<I", 32)  # 32 bits
        b.add_type("int", CTF_K_INTEGER, 0, 4, extra=int_enc)

        # Add struct with 2 members (id=2)
        # v3 small struct member: name_off(4) + packed(type<<16 | bit_offset)(4)
        m1_name = b.add_string("x")
        m2_name = b.add_string("y")
        members = struct.pack("<II", m1_name, (1 << 16) | 0)     # type=1, offset=0
        members += struct.pack("<II", m2_name, (1 << 16) | 32)   # type=1, offset=32
        b.add_type("point", CTF_K_STRUCT, 2, 8, extra=members)

        meta = parse_ctf_from_bytes(b.build())
        assert meta.has_ctf
        assert "point" in meta.structs

        s = meta.structs["point"]
        assert s.name == "point"
        assert s.byte_size == 8
        assert len(s.fields) == 2
        assert s.fields[0].name == "x"
        assert s.fields[0].byte_offset == 0
        assert s.fields[1].name == "y"
        assert s.fields[1].byte_offset == 4

    def test_union(self) -> None:
        b = CtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", CTF_K_INTEGER, 0, 4, extra=int_enc)

        m1_name = b.add_string("i")
        m2_name = b.add_string("f")
        members = struct.pack("<II", m1_name, (1 << 16) | 0)
        members += struct.pack("<II", m2_name, (1 << 16) | 0)
        b.add_type("my_union", CTF_K_UNION, 2, 4, extra=members)

        meta = parse_ctf_from_bytes(b.build())
        assert "my_union" in meta.structs
        assert meta.structs["my_union"].is_union

    def test_anonymous_struct_skipped(self) -> None:
        b = CtfBuilder()
        b.add_type("", CTF_K_STRUCT, 0, 0, extra=b"")
        meta = parse_ctf_from_bytes(b.build())
        assert len(meta.structs) == 0


# ---------------------------------------------------------------------------
# Full parse: enums
# ---------------------------------------------------------------------------

class TestCtfEnums:
    def test_simple_enum(self) -> None:
        b = CtfBuilder()
        e1_name = b.add_string("RED")
        e2_name = b.add_string("GREEN")
        e3_name = b.add_string("BLUE")
        entries = struct.pack("<Ii", e1_name, 0)
        entries += struct.pack("<Ii", e2_name, 1)
        entries += struct.pack("<Ii", e3_name, 2)
        b.add_type("color", CTF_K_ENUM, 3, 4, extra=entries)

        meta = parse_ctf_from_bytes(b.build())
        assert "color" in meta.enums
        e = meta.enums["color"]
        assert e.underlying_byte_size == 4
        assert e.members == {"RED": 0, "GREEN": 1, "BLUE": 2}

    def test_negative_enum_values(self) -> None:
        b = CtfBuilder()
        e_name = b.add_string("NEG")
        entries = struct.pack("<Ii", e_name, -42)
        b.add_type("signed_enum", CTF_K_ENUM, 1, 4, extra=entries)

        meta = parse_ctf_from_bytes(b.build())
        assert meta.enums["signed_enum"].members["NEG"] == -42


# ---------------------------------------------------------------------------
# Full parse: typedefs
# ---------------------------------------------------------------------------

class TestCtfTypedefs:
    def test_typedef(self) -> None:
        b = CtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", CTF_K_INTEGER, 0, 4, extra=int_enc)
        b.add_type("myint", CTF_K_TYPEDEF, 0, 1)  # typedef int myint

        meta = parse_ctf_from_bytes(b.build())
        assert meta.typedefs.get("myint") == "int"


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

class TestCtfCompression:
    def test_compressed_ctf(self) -> None:
        b = CtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", CTF_K_INTEGER, 0, 4, extra=int_enc)

        m_name = b.add_string("val")
        members = struct.pack("<II", m_name, (1 << 16) | 0)
        b.add_type("simple", CTF_K_STRUCT, 1, 4, extra=members)

        data = b.build(compress=True)
        meta = parse_ctf_from_bytes(data)
        assert meta.has_ctf
        assert "simple" in meta.structs


# ---------------------------------------------------------------------------
# to_dwarf_metadata conversion
# ---------------------------------------------------------------------------

class TestToDwarfMetadata:
    def test_conversion(self) -> None:
        b = CtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", CTF_K_INTEGER, 0, 4, extra=int_enc)
        m_name = b.add_string("val")
        members = struct.pack("<II", m_name, (1 << 16) | 0)
        b.add_type("simple", CTF_K_STRUCT, 1, 4, extra=members)

        meta = parse_ctf_from_bytes(b.build())
        dwarf = meta.to_dwarf_metadata()

        assert dwarf.has_dwarf
        assert "simple" in dwarf.structs


# ---------------------------------------------------------------------------
# Error handling / graceful degradation
# ---------------------------------------------------------------------------

class TestCtfErrorHandling:
    def test_empty_data(self) -> None:
        meta = parse_ctf_from_bytes(b"")
        assert not meta.has_ctf

    def test_bad_magic(self) -> None:
        meta = parse_ctf_from_bytes(b"\x00" * 100)
        assert not meta.has_ctf


# ---------------------------------------------------------------------------
# TypeMetadataSource protocol
# ---------------------------------------------------------------------------

class TestTypeMetadataSourceProtocol:
    def test_protocol_methods(self) -> None:
        b = CtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", CTF_K_INTEGER, 0, 4, extra=int_enc)
        m_name = b.add_string("x")
        members = struct.pack("<II", m_name, (1 << 16) | 0)
        b.add_type("point", CTF_K_STRUCT, 1, 4, extra=members)

        e_name = b.add_string("A")
        entries = struct.pack("<Ii", e_name, 0)
        b.add_type("my_enum", CTF_K_ENUM, 1, 4, extra=entries)

        meta = parse_ctf_from_bytes(b.build())

        assert meta.has_data is True
        assert meta.get_struct_layout("point") is not None
        assert meta.get_struct_layout("nonexistent") is None
        assert meta.get_enum_info("my_enum") is not None
        assert meta.get_enum_info("nonexistent") is None

    def test_isinstance_check(self) -> None:
        from abicheck.type_metadata import TypeMetadataSource
        meta = CtfMetadata(has_ctf=True)
        assert isinstance(meta, TypeMetadataSource)
