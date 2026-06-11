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

"""Unit tests for the fine-grained class-layout descriptor diff."""

from __future__ import annotations

from abicheck.checker import compare
from abicheck.checker_policy import BREAKING_KINDS, RISK_KINDS, ChangeKind
from abicheck.model import AbiSnapshot, RecordType


def _snap(version: str, *, types: list[RecordType]) -> AbiSnapshot:
    return AbiSnapshot(library="lib.so", version=version, types=types)


def _rec(name: str = "A", **kwargs: object) -> RecordType:
    """A public struct with a known size, plus any overridden layout fields."""
    defaults: dict[str, object] = dict(name=name, kind="struct", size_bits=128)
    defaults.update(kwargs)
    return RecordType(**defaults)  # type: ignore[arg-type]


def _kinds(old: AbiSnapshot, new: AbiSnapshot) -> set[ChangeKind]:
    return {c.kind for c in compare(old, new).changes}


class TestLayoutDescriptorDiff:
    def test_inert_on_default_snapshots(self) -> None:
        # Records with no layout descriptor populated (the default for every
        # existing snapshot) emit none of the new kinds.
        old = _snap("1", types=[_rec()])
        new = _snap("2", types=[_rec()])
        kinds = _kinds(old, new)
        for k in (
            ChangeKind.BASE_CLASS_OFFSET_CHANGED,
            ChangeKind.VPTR_INTRODUCED,
            ChangeKind.TRIVIALLY_COPYABLE_LOST,
            ChangeKind.STANDARD_LAYOUT_LOST,
            ChangeKind.TAIL_PADDING_REUSE_CHANGED,
            ChangeKind.LAYOUT_UNVERIFIABLE,
        ):
            assert k not in kinds

    def test_base_class_offset_changed(self) -> None:
        old = _snap("1", types=[_rec(base_offsets={"Base": 0})])
        new = _snap("2", types=[_rec(base_offsets={"Base": 64})])
        assert ChangeKind.BASE_CLASS_OFFSET_CHANGED in _kinds(old, new)
        assert ChangeKind.BASE_CLASS_OFFSET_CHANGED in BREAKING_KINDS

    def test_base_offset_unchanged_not_flagged(self) -> None:
        old = _snap("1", types=[_rec(base_offsets={"Base": 64})])
        new = _snap("2", types=[_rec(base_offsets={"Base": 64})])
        assert ChangeKind.BASE_CLASS_OFFSET_CHANGED not in _kinds(old, new)

    def test_base_offset_one_sided_not_flagged(self) -> None:
        # Base present only on the new side (not a *move*) → no finding.
        old = _snap("1", types=[_rec(base_offsets={})])
        new = _snap("2", types=[_rec(base_offsets={"Base": 64})])
        assert ChangeKind.BASE_CLASS_OFFSET_CHANGED not in _kinds(old, new)

    def test_vptr_introduced(self) -> None:
        old = _snap("1", types=[_rec(vptr_offset_bits=None)])
        new = _snap("2", types=[_rec(vptr_offset_bits=0)])
        assert ChangeKind.VPTR_INTRODUCED in _kinds(old, new)
        assert ChangeKind.VPTR_INTRODUCED in BREAKING_KINDS

    def test_vptr_present_both_sides_not_flagged(self) -> None:
        old = _snap("1", types=[_rec(vptr_offset_bits=0)])
        new = _snap("2", types=[_rec(vptr_offset_bits=0)])
        assert ChangeKind.VPTR_INTRODUCED not in _kinds(old, new)

    def test_trivially_copyable_lost(self) -> None:
        old = _snap("1", types=[_rec(is_trivially_copyable=True)])
        new = _snap("2", types=[_rec(is_trivially_copyable=False)])
        assert ChangeKind.TRIVIALLY_COPYABLE_LOST in _kinds(old, new)
        assert ChangeKind.TRIVIALLY_COPYABLE_LOST in BREAKING_KINDS

    def test_trivially_copyable_unknown_old_not_flagged(self) -> None:
        # Tri-state guard: old side unknown (None) → no finding.
        old = _snap("1", types=[_rec(is_trivially_copyable=None)])
        new = _snap("2", types=[_rec(is_trivially_copyable=False)])
        assert ChangeKind.TRIVIALLY_COPYABLE_LOST not in _kinds(old, new)

    def test_standard_layout_lost(self) -> None:
        old = _snap("1", types=[_rec(is_standard_layout=True)])
        new = _snap("2", types=[_rec(is_standard_layout=False)])
        kinds = _kinds(old, new)
        assert ChangeKind.STANDARD_LAYOUT_LOST in kinds
        assert ChangeKind.STANDARD_LAYOUT_LOST in RISK_KINDS

    def test_tail_padding_reuse_changed_at_stable_sizeof(self) -> None:
        # dsize changes while sizeof stays the same → tail-padding reuse risk.
        old = _snap("1", types=[_rec(size_bits=128, data_size_bits=96)])
        new = _snap("2", types=[_rec(size_bits=128, data_size_bits=120)])
        kinds = _kinds(old, new)
        assert ChangeKind.TAIL_PADDING_REUSE_CHANGED in kinds
        assert ChangeKind.TAIL_PADDING_REUSE_CHANGED in RISK_KINDS

    def test_tail_padding_not_flagged_when_sizeof_also_changed(self) -> None:
        # sizeof changed too → the coarse size detector owns it; we stay quiet.
        old = _snap("1", types=[_rec(size_bits=128, data_size_bits=96)])
        new = _snap("2", types=[_rec(size_bits=192, data_size_bits=160)])
        assert ChangeKind.TAIL_PADDING_REUSE_CHANGED not in _kinds(old, new)

    def test_layout_unverifiable_on_asymmetric_evidence(self) -> None:
        # New side carries a layout descriptor; old side has no size at all.
        old = _snap("1", types=[_rec(name="A", size_bits=None)])
        new = _snap("2", types=[_rec(name="A", size_bits=128, is_standard_layout=True)])
        kinds = _kinds(old, new)
        assert ChangeKind.LAYOUT_UNVERIFIABLE in kinds
        assert ChangeKind.LAYOUT_UNVERIFIABLE in RISK_KINDS

    def test_opaque_type_skipped(self) -> None:
        # An opaque/forward-declared side is owned by the incomplete-type
        # detectors, not the layout descriptor diff.
        old = _snap("1", types=[_rec(is_opaque=True, vptr_offset_bits=None)])
        new = _snap("2", types=[_rec(is_opaque=False, vptr_offset_bits=0)])
        assert ChangeKind.VPTR_INTRODUCED not in _kinds(old, new)

    def test_stdlib_record_not_flagged(self) -> None:
        # Toolchain-owned std:: records are excluded from public-surface
        # reasoning, so their layout churn does not produce a finding.
        old = _snap("1", types=[_rec(name="std::__1::thing", vptr_offset_bits=None)])
        new = _snap("2", types=[_rec(name="std::__1::thing", vptr_offset_bits=0)])
        assert ChangeKind.VPTR_INTRODUCED not in _kinds(old, new)
