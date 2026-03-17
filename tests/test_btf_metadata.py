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

"""Tests for BTF (BPF Type Format) parser."""
from __future__ import annotations

import struct

import pytest

from abicheck.btf_metadata import (
    BTF_KIND_CONST,
    BTF_KIND_ENUM,
    BTF_KIND_ENUM64,
    BTF_KIND_FUNC,
    BTF_KIND_FUNC_PROTO,
    BTF_KIND_INT,
    BTF_KIND_PTR,
    BTF_KIND_STRUCT,
    BTF_KIND_TYPEDEF,
    BTF_KIND_UNION,
    BTF_MAGIC,
    BTF_VERSION,
    BtfMetadata,
    FuncProto,
    _TypeResolver,
    _parse_header,
    _parse_types,
    _read_string,
    parse_btf_from_bytes,
)


# ---------------------------------------------------------------------------
# Helpers to build synthetic BTF blobs
# ---------------------------------------------------------------------------

class BtfBuilder:
    """Helper to construct synthetic BTF binary blobs for testing."""

    def __init__(self) -> None:
        self._strings = bytearray(b"\x00")  # string section starts with NUL
        self._type_entries: list[bytes] = []
        self._str_offsets: dict[str, int] = {"": 0}

    def add_string(self, s: str) -> int:
        """Add a string to the string table, return its offset."""
        if s in self._str_offsets:
            return self._str_offsets[s]
        off = len(self._strings)
        self._strings.extend(s.encode("utf-8") + b"\x00")
        self._str_offsets[s] = off
        return off

    def add_type(self, name: str, kind: int, vlen: int, size_or_type: int,
                 extra: bytes = b"", kflag: int = 0) -> int:
        """Add a type entry, return its 1-based type ID."""
        name_off = self.add_string(name) if name else 0
        info = (kflag << 31) | (kind << 24) | (vlen & 0xFFFF)
        entry = struct.pack("<III", name_off, info, size_or_type) + extra
        self._type_entries.append(entry)
        return len(self._type_entries)  # 1-based

    def build(self) -> bytes:
        """Build a complete BTF blob with header + types + strings."""
        type_data = b"".join(self._type_entries)
        str_data = bytes(self._strings)
        hdr_len = 24
        type_off = 0
        type_len = len(type_data)
        str_off = type_len
        str_len = len(str_data)
        header = struct.pack("<HBBIIIII",
                             BTF_MAGIC, BTF_VERSION, 0, hdr_len,
                             type_off, type_len, str_off, str_len)
        return header + type_data + str_data


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
        assert _read_string(b"abc\x00", -1) == ""


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

class TestParseHeader:
    def test_valid_header(self) -> None:
        b = BtfBuilder()
        data = b.build()
        hdr = _parse_header(data)
        assert hdr.magic == BTF_MAGIC
        assert hdr.version == BTF_VERSION
        assert hdr.hdr_len == 24

    def test_bad_magic(self) -> None:
        data = struct.pack("<HBBI", 0xDEAD, 1, 0, 24) + b"\x00" * 16
        with pytest.raises(ValueError, match="Bad BTF magic"):
            _parse_header(data)

    def test_too_small(self) -> None:
        with pytest.raises(ValueError, match="too small"):
            _parse_header(b"\x00" * 10)


# ---------------------------------------------------------------------------
# Type parsing
# ---------------------------------------------------------------------------

class TestParseTypes:
    def test_empty_section(self) -> None:
        types = _parse_types(b"")
        assert len(types) == 1  # only void sentinel
        assert types[0].type_id == 0

    def test_int_type(self) -> None:
        b = BtfBuilder()
        # INT encoding: bits=32, offset=0, signed
        int_enc = struct.pack("<I", (0 << 16) | (0 << 8) | 32)  # 32 bits
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)
        data = b.build()
        # Parse just the type section
        hdr = _parse_header(data)
        type_start = hdr.hdr_len + hdr.type_off
        type_end = type_start + hdr.type_len
        types = _parse_types(data[type_start:type_end])
        assert len(types) == 2  # void + int
        assert types[1].kind == BTF_KIND_INT


# ---------------------------------------------------------------------------
# Full parse: structs
# ---------------------------------------------------------------------------

class TestBtfStructs:
    def test_simple_struct(self) -> None:
        b = BtfBuilder()
        # Add INT type (id=1)
        int_enc = struct.pack("<I", 32)  # 32 bits
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)

        # Add struct with 2 members (id=2)
        # Member: name_off(4) + type(4) + offset(4)
        m1_name = b.add_string("x")
        m2_name = b.add_string("y")
        members = struct.pack("<III", m1_name, 1, 0)     # x: int at offset 0
        members += struct.pack("<III", m2_name, 1, 32)   # y: int at offset 32 bits
        b.add_type("point", BTF_KIND_STRUCT, 2, 8, extra=members)

        meta = parse_btf_from_bytes(b.build())
        assert meta.has_btf
        assert "point" in meta.structs

        s = meta.structs["point"]
        assert s.name == "point"
        assert s.byte_size == 8
        assert len(s.fields) == 2
        assert s.fields[0].name == "x"
        assert s.fields[0].byte_offset == 0
        assert s.fields[0].type_name == "int"
        assert s.fields[1].name == "y"
        assert s.fields[1].byte_offset == 4

    def test_union(self) -> None:
        b = BtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)

        m1_name = b.add_string("i")
        m2_name = b.add_string("f")
        members = struct.pack("<III", m1_name, 1, 0)
        members += struct.pack("<III", m2_name, 1, 0)
        b.add_type("my_union", BTF_KIND_UNION, 2, 4, extra=members)

        meta = parse_btf_from_bytes(b.build())
        assert "my_union" in meta.structs
        assert meta.structs["my_union"].is_union

    def test_bitfield_struct(self) -> None:
        b = BtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("unsigned int", BTF_KIND_INT, 0, 4, extra=int_enc)

        # kflag=1: offset encodes bitfield_size in bits 24-31
        m1_name = b.add_string("a")
        m2_name = b.add_string("b")
        # a: 3 bits at bit 0, b: 5 bits at bit 3
        m1_offset = (3 << 24) | 0   # bitfield_size=3, bit_offset=0
        m2_offset = (5 << 24) | 3   # bitfield_size=5, bit_offset=3
        members = struct.pack("<III", m1_name, 1, m1_offset)
        members += struct.pack("<III", m2_name, 1, m2_offset)
        b.add_type("flags", BTF_KIND_STRUCT, 2, 4, extra=members, kflag=1)

        meta = parse_btf_from_bytes(b.build())
        s = meta.structs["flags"]
        assert s.fields[0].bit_size == 3
        assert s.fields[1].bit_size == 5

    def test_anonymous_struct_skipped(self) -> None:
        b = BtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)
        # Struct with empty name (anonymous)
        b.add_type("", BTF_KIND_STRUCT, 0, 0, extra=b"")

        meta = parse_btf_from_bytes(b.build())
        assert len(meta.structs) == 0


# ---------------------------------------------------------------------------
# Full parse: enums
# ---------------------------------------------------------------------------

class TestBtfEnums:
    def test_simple_enum(self) -> None:
        b = BtfBuilder()
        e1_name = b.add_string("RED")
        e2_name = b.add_string("GREEN")
        e3_name = b.add_string("BLUE")
        entries = struct.pack("<Ii", e1_name, 0)
        entries += struct.pack("<Ii", e2_name, 1)
        entries += struct.pack("<Ii", e3_name, 2)
        b.add_type("color", BTF_KIND_ENUM, 3, 4, extra=entries)

        meta = parse_btf_from_bytes(b.build())
        assert "color" in meta.enums
        e = meta.enums["color"]
        assert e.underlying_byte_size == 4
        assert e.members == {"RED": 0, "GREEN": 1, "BLUE": 2}

    def test_enum64(self) -> None:
        b = BtfBuilder()
        e_name = b.add_string("BIG_VAL")
        # ENUM64: name_off(4) + val_lo(4) + val_hi(4)
        entries = struct.pack("<III", e_name, 0xDEADBEEF, 0x1)
        b.add_type("big_enum", BTF_KIND_ENUM64, 1, 8, extra=entries)

        meta = parse_btf_from_bytes(b.build())
        assert "big_enum" in meta.enums
        e = meta.enums["big_enum"]
        assert e.members["BIG_VAL"] == 0x1DEADBEEF

    def test_negative_enum_values(self) -> None:
        b = BtfBuilder()
        e_name = b.add_string("NEG")
        entries = struct.pack("<Ii", e_name, -1)
        b.add_type("signed_enum", BTF_KIND_ENUM, 1, 4, extra=entries)

        meta = parse_btf_from_bytes(b.build())
        assert meta.enums["signed_enum"].members["NEG"] == -1


# ---------------------------------------------------------------------------
# Full parse: function prototypes
# ---------------------------------------------------------------------------

class TestBtfFuncProtos:
    def test_function_proto(self) -> None:
        b = BtfBuilder()
        # Add int (id=1)
        int_enc = struct.pack("<I", 32)
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)

        # Add FUNC_PROTO: int(int, int) (id=2)
        p1_name = b.add_string("a")
        p2_name = b.add_string("b")
        params = struct.pack("<II", p1_name, 1)  # param a: int
        params += struct.pack("<II", p2_name, 1)  # param b: int
        b.add_type("", BTF_KIND_FUNC_PROTO, 2, 1, extra=params)  # returns int (type_id=1)

        # Add FUNC pointing to FUNC_PROTO (id=3)
        b.add_type("add", BTF_KIND_FUNC, 0, 2)  # size_or_type = proto type_id

        meta = parse_btf_from_bytes(b.build())
        assert "add" in meta.func_protos
        fp = meta.func_protos["add"]
        assert fp.return_type == "int"
        assert len(fp.params) == 2
        assert fp.params[0] == ("a", "int")
        assert fp.params[1] == ("b", "int")


# ---------------------------------------------------------------------------
# Full parse: typedefs
# ---------------------------------------------------------------------------

class TestBtfTypedefs:
    def test_typedef(self) -> None:
        b = BtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)
        b.add_type("myint", BTF_KIND_TYPEDEF, 0, 1)  # typedef int myint

        meta = parse_btf_from_bytes(b.build())
        assert meta.typedefs.get("myint") == "int"


# ---------------------------------------------------------------------------
# Type resolution
# ---------------------------------------------------------------------------

class TestTypeResolver:
    def test_pointer_name(self) -> None:
        b = BtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)
        b.add_type("", BTF_KIND_PTR, 0, 1)  # ptr to int

        data = b.build()
        hdr = _parse_header(data)
        type_start = hdr.hdr_len + hdr.type_off
        str_start = hdr.hdr_len + hdr.str_off
        str_end = str_start + hdr.str_len
        types = _parse_types(data[type_start:type_start + hdr.type_len])
        resolver = _TypeResolver(types, data[str_start:str_end])
        assert resolver.name(2) == "int *"
        assert resolver.size(2) == 8

    def test_const_name(self) -> None:
        b = BtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)
        b.add_type("", BTF_KIND_CONST, 0, 1)  # const int

        data = b.build()
        hdr = _parse_header(data)
        type_start = hdr.hdr_len + hdr.type_off
        str_start = hdr.hdr_len + hdr.str_off
        str_end = str_start + hdr.str_len
        types = _parse_types(data[type_start:type_start + hdr.type_len])
        resolver = _TypeResolver(types, data[str_start:str_end])
        assert resolver.name(2) == "const int"

    def test_void(self) -> None:
        b = BtfBuilder()
        data = b.build()
        hdr = _parse_header(data)
        types = _parse_types(b"")
        resolver = _TypeResolver(types, data[hdr.hdr_len + hdr.str_off:])
        assert resolver.name(0) == "void"
        assert resolver.size(0) == 0


# ---------------------------------------------------------------------------
# to_dwarf_metadata conversion
# ---------------------------------------------------------------------------

class TestToDwarfMetadata:
    def test_conversion(self) -> None:
        b = BtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)
        m_name = b.add_string("val")
        members = struct.pack("<III", m_name, 1, 0)
        b.add_type("simple", BTF_KIND_STRUCT, 1, 4, extra=members)

        meta = parse_btf_from_bytes(b.build())
        dwarf = meta.to_dwarf_metadata()

        assert dwarf.has_dwarf  # maps to has_btf
        assert "simple" in dwarf.structs
        assert dwarf.structs["simple"].name == "simple"


# ---------------------------------------------------------------------------
# Error handling / graceful degradation
# ---------------------------------------------------------------------------

class TestBtfErrorHandling:
    def test_empty_data(self) -> None:
        meta = parse_btf_from_bytes(b"")
        assert not meta.has_btf

    def test_bad_magic(self) -> None:
        meta = parse_btf_from_bytes(b"\x00" * 100)
        assert not meta.has_btf

    def test_truncated_types(self) -> None:
        # Valid header but type section is truncated
        b = BtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)
        data = b.build()
        # Truncate the data
        meta = parse_btf_from_bytes(data[:30])
        # Should degrade gracefully (empty or partial)
        assert isinstance(meta, BtfMetadata)


# ---------------------------------------------------------------------------
# TypeMetadataSource protocol
# ---------------------------------------------------------------------------

class TestTypeMetadataSourceProtocol:
    def test_protocol_methods(self) -> None:
        b = BtfBuilder()
        int_enc = struct.pack("<I", 32)
        b.add_type("int", BTF_KIND_INT, 0, 4, extra=int_enc)
        m_name = b.add_string("x")
        members = struct.pack("<III", m_name, 1, 0)
        b.add_type("point", BTF_KIND_STRUCT, 1, 4, extra=members)

        e_name = b.add_string("A")
        entries = struct.pack("<Ii", e_name, 0)
        b.add_type("my_enum", BTF_KIND_ENUM, 1, 4, extra=entries)

        meta = parse_btf_from_bytes(b.build())

        assert meta.has_data is True
        assert meta.get_struct_layout("point") is not None
        assert meta.get_struct_layout("nonexistent") is None
        assert meta.get_enum_info("my_enum") is not None
        assert meta.get_enum_info("nonexistent") is None

    def test_isinstance_check(self) -> None:
        from abicheck.type_metadata import TypeMetadataSource
        meta = BtfMetadata(has_btf=True)
        assert isinstance(meta, TypeMetadataSource)
