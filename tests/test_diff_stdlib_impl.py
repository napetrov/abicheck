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

"""Unit tests for the cross-implementation standard-library diff (D-stdlib)."""
from __future__ import annotations

from abicheck.build_mode import BuildMode, StdlibFamily
from abicheck.checker import compare
from abicheck.checker_policy import RISK_KINDS, ChangeKind
from abicheck.model import (
    AbiSnapshot,
    RecordType,
    TypeField,
    stdlib_namespaces_excluded,
)


def _snap(
    version: str,
    *,
    stdlib: StdlibFamily | None = None,
    libcpp_abi: int | None = None,
    types: list[RecordType] | None = None,
    build_mode: BuildMode | None | str = "auto",
) -> AbiSnapshot:
    """Build a minimal snapshot with an optional build-mode capture."""
    if build_mode == "auto":
        build_mode = (
            None
            if stdlib is None and libcpp_abi is None
            else BuildMode(
                stdlib=stdlib or StdlibFamily.UNKNOWN,
                libcpp_abi_version=libcpp_abi,
            )
        )
    return AbiSnapshot(
        library="libwidget.so.1",
        version=version,
        types=types or [],
        build_mode=build_mode,  # type: ignore[arg-type]
    )


def _embed_stdlib_record(size_bits: int | None = 192) -> RecordType:
    """A public class holding a std::vector by value (the canonical trap)."""
    return RecordType(
        name="Buffer",
        kind="class",
        size_bits=size_bits,
        fields=[TypeField(name="data", type="std::vector<int>", offset_bits=0)],
    )


# ---------------------------------------------------------------------------
# stdlib_namespaces_excluded — the global std:: filter must stay ON even for a
# cross-implementation comparison (Codex review on PR #345): standalone std::
# records differ wholesale between libstdc++/libc++, so un-filtering them
# globally would flood BREAKING noise for toolchain-owned internals. The real
# break is caught via the (non-std::) owner type; the hazard is surfaced as a
# RISK build-mode finding.
# ---------------------------------------------------------------------------
class TestGlobalFilterPreserved:
    def test_same_toolchain_filters_stdlib(self) -> None:
        old = _snap("1", stdlib=StdlibFamily.LIBSTDCXX)
        new = _snap("2", stdlib=StdlibFamily.LIBSTDCXX)
        assert stdlib_namespaces_excluded(old, new) is True

    def test_cross_implementation_does_not_disable_global_filter(self) -> None:
        # Regression guard: a cross-impl build-mode must NOT relax the filter.
        old = _snap("1", stdlib=StdlibFamily.LIBSTDCXX)
        new = _snap("2", stdlib=StdlibFamily.LIBCXX)
        assert stdlib_namespaces_excluded(old, new) is True

    def test_no_build_mode_keeps_filtering(self) -> None:
        old = _snap("1", build_mode=None)
        new = _snap("2", build_mode=None)
        assert stdlib_namespaces_excluded(old, new) is True


# ---------------------------------------------------------------------------
# Detector findings via compare()
# ---------------------------------------------------------------------------
class TestDetectorFindings:
    def test_stdlib_implementation_change_is_risk(self) -> None:
        old = _snap("1", stdlib=StdlibFamily.LIBSTDCXX, types=[_embed_stdlib_record()])
        new = _snap("2", stdlib=StdlibFamily.LIBCXX, types=[_embed_stdlib_record()])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.STDLIB_IMPLEMENTATION_CHANGED in kinds
        # RISK, not BREAKING — never escalate on its own.
        assert ChangeKind.STDLIB_IMPLEMENTATION_CHANGED in RISK_KINDS

    def test_libcpp_abi_version_change_emitted(self) -> None:
        old = _snap("1", stdlib=StdlibFamily.LIBCXX, libcpp_abi=1)
        new = _snap("2", stdlib=StdlibFamily.LIBCXX, libcpp_abi=2)
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.LIBCPP_ABI_VERSION_CHANGED in kinds

    def test_silent_without_build_mode(self) -> None:
        old = _snap("1", build_mode=None, types=[_embed_stdlib_record()])
        new = _snap("2", build_mode=None, types=[_embed_stdlib_record()])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.STDLIB_IMPLEMENTATION_CHANGED not in kinds
        assert ChangeKind.LIBCPP_ABI_VERSION_CHANGED not in kinds

    def test_same_implementation_emits_nothing(self) -> None:
        old = _snap("1", stdlib=StdlibFamily.LIBSTDCXX, types=[_embed_stdlib_record()])
        new = _snap("2", stdlib=StdlibFamily.LIBSTDCXX, types=[_embed_stdlib_record()])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.STDLIB_IMPLEMENTATION_CHANGED not in kinds

    def test_no_layout_evidence_notes_gap_quietly(self) -> None:
        # No size_bits anywhere → layout unverifiable; finding still RISK and
        # its description must mention the missing evidence without escalating.
        old = _snap(
            "1",
            stdlib=StdlibFamily.LIBSTDCXX,
            types=[_embed_stdlib_record(size_bits=None)],
        )
        new = _snap(
            "2",
            stdlib=StdlibFamily.LIBCXX,
            types=[_embed_stdlib_record(size_bits=None)],
        )
        result = compare(old, new)
        finding = next(
            c for c in result.changes
            if c.kind == ChangeKind.STDLIB_IMPLEMENTATION_CHANGED
        )
        assert "no layout evidence" in finding.description.lower()

    def test_change_without_embedding_emits_base_description(self) -> None:
        # stdlib changes but no public type embeds a std:: type by value → still
        # a RISK finding, but the description carries no embed-specific note.
        old = _snap("1", stdlib=StdlibFamily.LIBSTDCXX, types=[])
        new = _snap("2", stdlib=StdlibFamily.LIBCXX, types=[])
        result = compare(old, new)
        finding = next(
            c for c in result.changes
            if c.kind == ChangeKind.STDLIB_IMPLEMENTATION_CHANGED
        )
        assert "embeds a std::" not in finding.description
        assert finding.old_value == "libstdc++" and finding.new_value == "libc++"

    def test_stdlib_field_by_pointer_is_not_embedding(self) -> None:
        # A std:: member held by pointer is layout-neutral, so it must NOT count
        # as an embedding (no embed note in the description).
        rec = RecordType(
            name="Handle",
            kind="class",
            size_bits=64,
            fields=[TypeField(name="vec", type="std::vector<int> *", offset_bits=0)],
        )
        old = _snap("1", stdlib=StdlibFamily.LIBSTDCXX, types=[rec])
        new = _snap("2", stdlib=StdlibFamily.LIBCXX, types=[rec])
        result = compare(old, new)
        finding = next(
            c for c in result.changes
            if c.kind == ChangeKind.STDLIB_IMPLEMENTATION_CHANGED
        )
        assert "embeds a std::" not in finding.description

    def test_msvc_stl_label_in_description(self) -> None:
        old = _snap("1", stdlib=StdlibFamily.MSVC_STL, types=[_embed_stdlib_record()])
        new = _snap("2", stdlib=StdlibFamily.LIBCXX, types=[_embed_stdlib_record()])
        result = compare(old, new)
        finding = next(
            c for c in result.changes
            if c.kind == ChangeKind.STDLIB_IMPLEMENTATION_CHANGED
        )
        assert "MSVC STL" in finding.description
