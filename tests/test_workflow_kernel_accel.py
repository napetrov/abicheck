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

"""Workflow-level scenarios for kernel (BTF) and accelerator (SYCL) stacks — G6.

The BTF and SYCL *parsers* are unit-tested elsewhere; these tests drive the
canonical *workflows* end-to-end through the standard ``compare`` + report path
so the use cases are validated as flows, not just parsers:

- **Kernel / eBPF (BTF):** a kernel struct gains a field (the out-of-tree
  "module vs ``vmlinux`` BTF" break). Real BTF bytes are parsed by
  :func:`parse_btf_from_bytes`, converted to the checker's type metadata, and
  run through ``compare`` — the layout detectors fire format-agnostically.
- **SYCL / heterogeneous (PI/UR):** a plugin-interface entrypoint is dropped,
  driven through ``compare`` and the reporter (not just the ``diff_sycl`` unit
  detector).

See docs/development/usecase-coverage-evaluation.md (gap G6) and
docs/user-guide/kernel-btf.md.
"""

from __future__ import annotations

import struct

from abicheck.btf_metadata import (
    BTF_KIND_INT,
    BTF_KIND_STRUCT,
    BTF_MAGIC,
    BTF_VERSION,
    parse_btf_from_bytes,
)
from abicheck.checker import compare
from abicheck.checker_policy import ChangeKind, Verdict
from abicheck.model import AbiSnapshot
from abicheck.reporter import to_json, to_markdown
from abicheck.sycl_metadata import SyclMetadata, SyclPluginInfo

# ── BTF blob builder (minimal, self-contained) ───────────────────────────────


class _BtfBlob:
    """Build a minimal BTF blob: one INT type plus one struct."""

    def __init__(self) -> None:
        self._strings = bytearray(b"\x00")
        self._types: list[bytes] = []
        self._offsets: dict[str, int] = {"": 0}

    def _str(self, s: str) -> int:
        if s in self._offsets:
            return self._offsets[s]
        off = len(self._strings)
        self._strings.extend(s.encode() + b"\x00")
        self._offsets[s] = off
        return off

    def _add(self, name: str, kind: int, vlen: int, size: int, extra: bytes = b"") -> int:
        info = (kind << 24) | (vlen & 0xFFFF)
        self._types.append(struct.pack("<III", self._str(name) if name else 0, info, size) + extra)
        return len(self._types)

    def build_struct(self, struct_name: str, n_fields: int) -> bytes:
        """A struct with ``n_fields`` int members (each 4 bytes / 32 bits)."""
        self._add("int", BTF_KIND_INT, 0, 4, extra=struct.pack("<I", 32))
        members = b""
        for i in range(n_fields):
            members += struct.pack("<III", self._str(f"f{i}"), 1, i * 32)
        self._add(struct_name, BTF_KIND_STRUCT, n_fields, n_fields * 4, extra=members)
        type_data = b"".join(self._types)
        str_data = bytes(self._strings)
        header = struct.pack(
            "<HBBIIIII", BTF_MAGIC, BTF_VERSION, 0, 24,
            0, len(type_data), len(type_data), len(str_data),
        )
        return header + type_data + str_data


def _btf_snapshot(version: str, struct_name: str, n_fields: int) -> AbiSnapshot:
    meta = parse_btf_from_bytes(_BtfBlob().build_struct(struct_name, n_fields))
    return AbiSnapshot(library="vmlinux", version=version, dwarf=meta.to_dwarf_metadata())


# ── Scenario: kernel struct layout change via BTF ─────────────────────────────


def test_btf_struct_gains_field_is_breaking_through_compare() -> None:
    """A kernel struct that gains a field is an out-of-tree-module ABI break and
    flows through ``compare`` as a layout change with the real BTF parser."""
    old = _btf_snapshot("5.10", "task_state", n_fields=2)
    new = _btf_snapshot("5.11", "task_state", n_fields=3)  # gains a field

    result = compare(old, new)

    assert result.verdict is Verdict.BREAKING
    kinds = {c.kind for c in result.changes}
    assert ChangeKind.STRUCT_SIZE_CHANGED in kinds


def test_btf_identical_structs_are_no_change() -> None:
    old = _btf_snapshot("5.10", "task_state", n_fields=3)
    new = _btf_snapshot("5.10", "task_state", n_fields=3)

    result = compare(old, new)
    assert result.verdict in (Verdict.NO_CHANGE, Verdict.COMPATIBLE)
    assert not any(c.kind is ChangeKind.STRUCT_SIZE_CHANGED for c in result.changes)


# ── Scenario: SYCL plugin-interface change ────────────────────────────────────


def _sycl_snapshot(version: str, entry_points: list[str]) -> AbiSnapshot:
    plugin = SyclPluginInfo(
        name="level_zero",
        library="libpi_level_zero.so",
        interface_type="pi",
        pi_version="1.2",
        entry_points=entry_points,
        backend_type="level_zero",
    )
    sycl = SyclMetadata(
        implementation="dpcpp",
        runtime_version="",
        pi_version="1.2",
        plugins=[plugin],
        plugin_search_paths=["/usr/lib/sycl"],
    )
    return AbiSnapshot(library="libsycl.so", version=version, sycl=sycl)


def test_sycl_entrypoint_drop_is_breaking_and_reaches_reports() -> None:
    old = _sycl_snapshot("1", ["piPluginInit", "piPlatformsGet", "piDevicesGet"])
    new = _sycl_snapshot("2", ["piPluginInit", "piPlatformsGet"])  # drops piDevicesGet

    result = compare(old, new)
    assert result.verdict is Verdict.BREAKING
    assert any(c.kind is ChangeKind.SYCL_PI_ENTRYPOINT_REMOVED for c in result.changes)

    # The finding reaches the standard report path (JSON + Markdown), not just
    # the diff_sycl unit detector.
    import json as _json
    payload = _json.loads(to_json(result))
    assert payload["verdict"] == "BREAKING"
    assert "piDevicesGet" in to_markdown(result)


def test_sycl_additive_entrypoint_is_not_breaking() -> None:
    old = _sycl_snapshot("1", ["piPluginInit", "piPlatformsGet"])
    new = _sycl_snapshot("2", ["piPluginInit", "piPlatformsGet", "piDevicesGet"])

    result = compare(old, new)
    assert result.verdict is not Verdict.BREAKING
