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

"""Unit tests for macho_metadata — dataclass construction, magic detection, and serialization."""
from __future__ import annotations

from abicheck.macho_metadata import (
    MachoExport,
    MachoMetadata,
    MachoSymbolType,
    _version_str,
    is_macho,
)

# ── MachoMetadata dataclass ─────────────────────────────────────────────

class TestMachoMetadataDataclass:
    def test_default_construction(self):
        meta = MachoMetadata()
        assert meta.cpu_type == ""
        assert meta.filetype == ""
        assert meta.flags == 0
        assert meta.install_name == ""
        assert meta.dependent_libs == []
        assert meta.reexported_libs == []
        assert meta.exports == []
        assert meta.current_version == ""
        assert meta.compat_version == ""
        assert meta.min_os_version == ""

    def test_export_map_cached_property(self):
        e1 = MachoExport(name="foo")
        e2 = MachoExport(name="bar")
        e3 = MachoExport(name="")  # nameless
        meta = MachoMetadata(exports=[e1, e2, e3])
        em = meta.export_map
        assert em == {"foo": e1, "bar": e2}
        assert meta.export_map is em

    def test_macho_export_defaults(self):
        exp = MachoExport(name="test")
        assert exp.sym_type == MachoSymbolType.EXPORTED
        assert exp.is_weak is False

    def test_macho_export_weak(self):
        exp = MachoExport(name="weak_fn", sym_type=MachoSymbolType.WEAK, is_weak=True)
        assert exp.sym_type == MachoSymbolType.WEAK
        assert exp.is_weak is True


# ── _version_str ────────────────────────────────────────────────────────

class TestVersionStr:
    def test_simple_version(self):
        # 1.2.3 → major=1, minor=2, patch=3
        packed = (1 << 16) | (2 << 8) | 3
        assert _version_str(packed) == "1.2.3"

    def test_zero_version(self):
        assert _version_str(0) == "0.0.0"

    def test_high_major(self):
        packed = (10 << 16) | (0 << 8) | 0
        assert _version_str(packed) == "10.0.0"


# ── is_macho magic detection ────────────────────────────────────────────

class TestIsMacho:
    def test_macho_64_le(self, tmp_path):
        p = tmp_path / "lib.dylib"
        p.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 100)
        assert is_macho(p) is True

    def test_macho_64_be(self, tmp_path):
        p = tmp_path / "lib.dylib"
        p.write_bytes(b"\xfe\xed\xfa\xcf" + b"\x00" * 100)
        assert is_macho(p) is True

    def test_macho_32_le(self, tmp_path):
        p = tmp_path / "lib.dylib"
        p.write_bytes(b"\xce\xfa\xed\xfe" + b"\x00" * 100)
        assert is_macho(p) is True

    def test_macho_32_be(self, tmp_path):
        p = tmp_path / "lib.dylib"
        p.write_bytes(b"\xfe\xed\xfa\xce" + b"\x00" * 100)
        assert is_macho(p) is True

    def test_fat_binary(self, tmp_path):
        p = tmp_path / "lib.dylib"
        p.write_bytes(b"\xca\xfe\xba\xbe" + b"\x00" * 100)
        assert is_macho(p) is True

    def test_fat_binary_swapped(self, tmp_path):
        p = tmp_path / "lib.dylib"
        p.write_bytes(b"\xbe\xba\xfe\xca" + b"\x00" * 100)
        assert is_macho(p) is True

    def test_elf_not_macho(self, tmp_path):
        p = tmp_path / "lib.so"
        p.write_bytes(b"\x7fELF" + b"\x00" * 100)
        assert is_macho(p) is False

    def test_pe_not_macho(self, tmp_path):
        p = tmp_path / "test.dll"
        p.write_bytes(b"MZ" + b"\x00" * 100)
        assert is_macho(p) is False

    def test_nonexistent_file(self, tmp_path):
        p = tmp_path / "nope.dylib"
        assert is_macho(p) is False

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.dylib"
        p.write_bytes(b"")
        assert is_macho(p) is False

    def test_short_file(self, tmp_path):
        p = tmp_path / "short.dylib"
        p.write_bytes(b"\xcf\xfa")
        assert is_macho(p) is False


# ── Serialization round-trip ─────────────────────────────────────────────

class TestMachoSerialization:
    def test_snapshot_roundtrip(self):
        from abicheck.model import AbiSnapshot
        from abicheck.serialization import snapshot_from_dict, snapshot_to_dict

        macho = MachoMetadata(
            cpu_type="ARM64",
            filetype="MH_DYLIB",
            flags=0x00200085,
            install_name="/usr/lib/libfoo.1.dylib",
            dependent_libs=["/usr/lib/libSystem.B.dylib"],
            reexported_libs=[],
            exports=[
                MachoExport(name="foo_init"),
                MachoExport(name="foo_weak", sym_type=MachoSymbolType.WEAK, is_weak=True),
            ],
            current_version="1.2.3",
            compat_version="1.0.0",
            min_os_version="11.0.0",
        )
        snap = AbiSnapshot(library="libfoo.dylib", version="1.2.3", macho=macho)
        d = snapshot_to_dict(snap)
        assert d["macho"]["cpu_type"] == "ARM64"
        assert len(d["macho"]["exports"]) == 2
        assert d["macho"]["exports"][1]["sym_type"] == "weak"

        snap2 = snapshot_from_dict(d)
        assert snap2.macho is not None
        assert snap2.macho.cpu_type == "ARM64"
        assert len(snap2.macho.exports) == 2
        assert snap2.macho.exports[1].sym_type == MachoSymbolType.WEAK
        assert snap2.macho.exports[1].is_weak is True
        assert snap2.macho.install_name == "/usr/lib/libfoo.1.dylib"
        assert snap2.macho.dependent_libs == ["/usr/lib/libSystem.B.dylib"]


# ── Checker diff_macho ───────────────────────────────────────────────────

class TestDiffMacho:
    def test_removed_export(self):
        from abicheck.checker import ChangeKind, _diff_macho
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="libfoo.dylib", version="1.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo"), MachoExport(name="bar")],
        ))
        new = AbiSnapshot(library="libfoo.dylib", version="2.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo")],
        ))
        changes = _diff_macho(old, new)
        removed = [c for c in changes if c.kind == ChangeKind.FUNC_REMOVED]
        assert len(removed) == 1
        assert removed[0].symbol == "bar"

    def test_added_export(self):
        from abicheck.checker import ChangeKind, _diff_macho
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="libfoo.dylib", version="1.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo")],
        ))
        new = AbiSnapshot(library="libfoo.dylib", version="2.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo"), MachoExport(name="baz")],
        ))
        changes = _diff_macho(old, new)
        added = [c for c in changes if c.kind == ChangeKind.FUNC_ADDED]
        assert len(added) == 1
        assert added[0].symbol == "baz"

    def test_install_name_change(self):
        from abicheck.checker import ChangeKind, _diff_macho
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="libfoo.dylib", version="1.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo")],
            install_name="/usr/lib/libfoo.1.dylib",
        ))
        new = AbiSnapshot(library="libfoo.dylib", version="2.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo")],
            install_name="/usr/lib/libfoo.2.dylib",
        ))
        changes = _diff_macho(old, new)
        soname = [c for c in changes if c.kind == ChangeKind.SONAME_CHANGED
                  and c.symbol == "LC_ID_DYLIB"]
        assert len(soname) == 1
        assert soname[0].old_value == "/usr/lib/libfoo.1.dylib"
        assert soname[0].new_value == "/usr/lib/libfoo.2.dylib"

    def test_compat_version_change(self):
        from abicheck.checker import _diff_macho
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="libfoo.dylib", version="1.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo")],
            compat_version="1.0.0",
        ))
        new = AbiSnapshot(library="libfoo.dylib", version="2.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo")],
            compat_version="2.0.0",
        ))
        changes = _diff_macho(old, new)
        compat = [c for c in changes if c.symbol == "compat_version"]
        assert len(compat) == 1

    def test_dependency_changes(self):
        from abicheck.checker import ChangeKind, _diff_macho
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="libfoo.dylib", version="1.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo")],
            dependent_libs=["/usr/lib/libSystem.B.dylib", "/usr/lib/libz.1.dylib"],
        ))
        new = AbiSnapshot(library="libfoo.dylib", version="2.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo")],
            dependent_libs=["/usr/lib/libSystem.B.dylib", "/usr/lib/libc++.1.dylib"],
        ))
        changes = _diff_macho(old, new)
        removed = [c for c in changes if c.kind == ChangeKind.NEEDED_REMOVED]
        added = [c for c in changes if c.kind == ChangeKind.NEEDED_ADDED]
        assert len(removed) == 1
        assert "/usr/lib/libz.1.dylib" in removed[0].symbol
        assert len(added) == 1
        assert "/usr/lib/libc++.1.dylib" in added[0].symbol

    def test_no_changes(self):
        from abicheck.checker import _diff_macho
        from abicheck.model import AbiSnapshot

        macho = MachoMetadata(exports=[MachoExport(name="foo")])
        old = AbiSnapshot(library="libfoo.dylib", version="1.0", macho=macho)
        new = AbiSnapshot(library="libfoo.dylib", version="2.0", macho=MachoMetadata(
            exports=[MachoExport(name="foo")],
        ))
        assert _diff_macho(old, new) == []

    def test_empty_macho_metadata(self):
        from abicheck.checker import _diff_macho
        from abicheck.model import AbiSnapshot

        old = AbiSnapshot(library="libfoo.dylib", version="1.0", macho=MachoMetadata())
        new = AbiSnapshot(library="libfoo.dylib", version="2.0", macho=MachoMetadata())
        assert _diff_macho(old, new) == []
