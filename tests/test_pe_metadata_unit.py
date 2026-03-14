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

"""Unit tests for pe_metadata — dataclass construction, magic detection, and serialization."""
from __future__ import annotations

import struct
from pathlib import Path

from abicheck.pe_metadata import (
    PeExport,
    PeMetadata,
    PeSymbolType,
    is_pe,
)

# ── PeMetadata dataclass ────────────────────────────────────────────────

class TestPeMetadataDataclass:
    def test_default_construction(self):
        meta = PeMetadata()
        assert meta.machine == ""
        assert meta.characteristics == 0
        assert meta.dll_characteristics == 0
        assert meta.exports == []
        assert meta.imports == {}
        assert meta.file_version == ""
        assert meta.product_version == ""

    def test_export_map_cached_property(self):
        e1 = PeExport(name="foo", ordinal=1)
        e2 = PeExport(name="bar", ordinal=2)
        e3 = PeExport(name="", ordinal=3)  # nameless export
        meta = PeMetadata(exports=[e1, e2, e3])
        em = meta.export_map
        assert em == {"foo": e1, "bar": e2}
        # Cached — same object
        assert meta.export_map is em

    def test_pe_export_defaults(self):
        exp = PeExport(name="test")
        assert exp.ordinal == 0
        assert exp.sym_type == PeSymbolType.EXPORTED
        assert exp.forwarder == ""

    def test_pe_export_forwarded(self):
        exp = PeExport(name="func", ordinal=5, sym_type=PeSymbolType.FORWARDED,
                       forwarder="NTDLL.RtlFoo")
        assert exp.sym_type == PeSymbolType.FORWARDED
        assert exp.forwarder == "NTDLL.RtlFoo"


# ── is_pe magic detection ───────────────────────────────────────────────

def _make_pe_file(tmp_path: Path, pe_offset: int = 0x80) -> Path:
    """Create a minimal file with valid PE magic bytes."""
    p = tmp_path / "test.dll"
    data = bytearray(pe_offset + 4)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset:pe_offset + 4] = b"PE\x00\x00"
    p.write_bytes(bytes(data))
    return p


class TestIsPe:
    def test_valid_pe_file(self, tmp_path):
        p = _make_pe_file(tmp_path)
        assert is_pe(p) is True

    def test_non_pe_file(self, tmp_path):
        p = tmp_path / "notpe.bin"
        p.write_bytes(b"\x00" * 256)
        assert is_pe(p) is False

    def test_mz_without_pe_signature(self, tmp_path):
        p = tmp_path / "fakemz.bin"
        data = bytearray(256)
        data[0:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        # No PE\0\0 at offset 0x80
        p.write_bytes(bytes(data))
        assert is_pe(p) is False

    def test_truncated_file(self, tmp_path):
        p = tmp_path / "short.bin"
        p.write_bytes(b"MZ")
        assert is_pe(p) is False

    def test_nonexistent_file(self, tmp_path):
        p = tmp_path / "nope.dll"
        assert is_pe(p) is False

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.dll"
        p.write_bytes(b"")
        assert is_pe(p) is False

    def test_elf_file_not_pe(self, tmp_path):
        p = tmp_path / "lib.so"
        p.write_bytes(b"\x7fELF" + b"\x00" * 100)
        assert is_pe(p) is False


# ── Serialization round-trip ─────────────────────────────────────────────

class TestPeSerialization:
    def test_snapshot_roundtrip(self):
        from abicheck.model import AbiSnapshot
        from abicheck.serialization import snapshot_from_dict, snapshot_to_dict

        pe = PeMetadata(
            machine="IMAGE_FILE_MACHINE_AMD64",
            characteristics=0x2022,
            dll_characteristics=0x8160,
            exports=[
                PeExport(name="init", ordinal=1),
                PeExport(name="fwd", ordinal=2, sym_type=PeSymbolType.FORWARDED,
                         forwarder="OTHER.init"),
            ],
            imports={"KERNEL32.dll": ["LoadLibraryA", "GetProcAddress"]},
            file_version="1.0.0.0",
            product_version="1.0.0.0",
        )
        snap = AbiSnapshot(library="test.dll", version="1.0", pe=pe)
        d = snapshot_to_dict(snap)
        assert d["pe"]["machine"] == "IMAGE_FILE_MACHINE_AMD64"
        assert len(d["pe"]["exports"]) == 2
        assert d["pe"]["exports"][1]["sym_type"] == "forwarded"

        snap2 = snapshot_from_dict(d)
        assert snap2.pe is not None
        assert snap2.pe.machine == "IMAGE_FILE_MACHINE_AMD64"
        assert len(snap2.pe.exports) == 2
        assert snap2.pe.exports[1].sym_type == PeSymbolType.FORWARDED
        assert snap2.pe.exports[1].forwarder == "OTHER.init"
        assert snap2.pe.imports == {"KERNEL32.dll": ["LoadLibraryA", "GetProcAddress"]}


# ── Checker diff_pe ──────────────────────────────────────────────────────

class TestDiffPe:
    def test_removed_export(self):
        from abicheck.checker import ChangeKind, _diff_pe
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="test.dll", version="1.0", pe=PeMetadata(
            exports=[PeExport(name="foo"), PeExport(name="bar")],
        ))
        new = AbiSnapshot(library="test.dll", version="2.0", pe=PeMetadata(
            exports=[PeExport(name="foo")],
        ))
        changes = _diff_pe(old, new)
        removed = [c for c in changes if c.kind == ChangeKind.FUNC_REMOVED]
        assert len(removed) == 1
        assert removed[0].symbol == "bar"

    def test_added_export(self):
        from abicheck.checker import ChangeKind, _diff_pe
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="test.dll", version="1.0", pe=PeMetadata(
            exports=[PeExport(name="foo")],
        ))
        new = AbiSnapshot(library="test.dll", version="2.0", pe=PeMetadata(
            exports=[PeExport(name="foo"), PeExport(name="baz")],
        ))
        changes = _diff_pe(old, new)
        added = [c for c in changes if c.kind == ChangeKind.FUNC_ADDED]
        assert len(added) == 1
        assert added[0].symbol == "baz"

    def test_import_dependency_changes(self):
        from abicheck.checker import ChangeKind, _diff_pe
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="test.dll", version="1.0", pe=PeMetadata(
            exports=[PeExport(name="x")],
            imports={"KERNEL32.dll": ["LoadLibraryA"], "USER32.dll": ["MessageBoxA"]},
        ))
        new = AbiSnapshot(library="test.dll", version="2.0", pe=PeMetadata(
            exports=[PeExport(name="x")],
            imports={"KERNEL32.dll": ["LoadLibraryA"], "ADVAPI32.dll": ["RegOpenKeyA"]},
        ))
        changes = _diff_pe(old, new)
        removed = [c for c in changes if c.kind == ChangeKind.NEEDED_REMOVED]
        added = [c for c in changes if c.kind == ChangeKind.NEEDED_ADDED]
        assert len(removed) == 1
        assert removed[0].symbol == "USER32.dll"
        assert len(added) == 1
        assert added[0].symbol == "ADVAPI32.dll"

    def test_no_changes(self):
        from abicheck.checker import _diff_pe
        from abicheck.model import AbiSnapshot

        pe = PeMetadata(exports=[PeExport(name="foo")])
        old = AbiSnapshot(library="test.dll", version="1.0", pe=pe)
        new = AbiSnapshot(library="test.dll", version="2.0", pe=PeMetadata(
            exports=[PeExport(name="foo")],
        ))
        assert _diff_pe(old, new) == []

    def test_empty_pe_metadata(self):
        from abicheck.checker import _diff_pe
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="test.dll", version="1.0", pe=PeMetadata())
        new = AbiSnapshot(library="test.dll", version="2.0", pe=PeMetadata())
        assert _diff_pe(old, new) == []
