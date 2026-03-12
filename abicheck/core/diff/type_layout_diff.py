"""type_layout_diff — Phase 1b diff engine module.

Two-phase diff for struct/class type layouts:
  Phase 1: Structural hash filter — O(N), eliminates unchanged types
  Phase 2: Deep diff — only on types whose hash changed

This prevents the O(N²) / unbounded graph traversal that naive type
comparison would require for large C++ libraries.

Pipeline position: corpus → **diff** → suppress → policy
"""
from __future__ import annotations

from abicheck.core.corpus.normalizer import NormalizedSnapshot
from abicheck.core.model import (
    Change,
    ChangeKind,
    ChangeSeverity,
    EntitySnapshot,
    Origin,
)
from abicheck.model import RecordType

# ---------------------------------------------------------------------------
# Structural hash (phase 1 filter)
# ---------------------------------------------------------------------------

def _type_structural_hash(t: RecordType) -> int:
    """Fast structural hash for pre-filtering unchanged types.

    Hashes: kind, size_bits, field count, field names+types (shallow).
    Intentionally avoids recursion — deep comparison happens in phase 2.
    """
    field_sig = tuple(
        (f.name, f.type, f.offset_bits, f.is_bitfield, f.bitfield_bits)
        for f in t.fields
    )
    return hash((
        t.name,
        t.kind,
        t.size_bits,
        t.alignment_bits,
        len(t.fields),
        field_sig,
        tuple(t.bases),
        tuple(t.vtable),
    ))


# ---------------------------------------------------------------------------
# Type snapshot helpers
# ---------------------------------------------------------------------------

def _type_snapshot(t: RecordType) -> EntitySnapshot:
    return EntitySnapshot(
        entity_repr=f"{t.kind} {t.name} (size={t.size_bits})",
        raw={
            "kind": t.kind,
            "size_bits": t.size_bits,
            "alignment_bits": t.alignment_bits,
            "field_count": len(t.fields),
            "bases": list(t.bases),
            "vtable_length": len(t.vtable),
        },
    )


# ---------------------------------------------------------------------------
# Deep type diff (phase 2)
# ---------------------------------------------------------------------------

def _diff_type_pair(t_old: RecordType, t_new: RecordType) -> list[Change]:
    """Deep diff between two versions of the same type.

    Called only when structural hash shows a difference.
    """
    changes: list[Change] = []

    snap_old = _type_snapshot(t_old)
    snap_new = _type_snapshot(t_new)

    # Size change (distinct ChangeKind from field layout)
    if t_old.size_bits != t_new.size_bits:
        changes.append(Change(
            change_kind=ChangeKind.SIZE_CHANGE,
            entity_type="type",
            entity_name=t_old.name,
            before=snap_old,
            after=snap_new,
            severity=ChangeSeverity.BREAK,
            origin=Origin.CASTXML,
            confidence=0.95,
        ))

    # Field layout changes
    changes.extend(_diff_fields(t_old, t_new))

    # Base class changes — compare as tuples to catch reordering
    if tuple(t_old.bases) != tuple(t_new.bases):
        changes.append(Change(
            change_kind=ChangeKind.TYPE_LAYOUT,
            entity_type="type",
            entity_name=t_old.name,
            before=EntitySnapshot(entity_repr=f"bases={list(t_old.bases)}"),
            after=EntitySnapshot(entity_repr=f"bases={list(t_new.bases)}"),
            severity=ChangeSeverity.BREAK,
            origin=Origin.CASTXML,
            confidence=0.9,
        ))

    # Vtable changes
    if t_old.vtable != t_new.vtable:
        changes.append(Change(
            change_kind=ChangeKind.VTABLE_INHERITANCE,
            entity_type="type",
            entity_name=t_old.name,
            before=EntitySnapshot(
                entity_repr=f"vtable={t_old.vtable}",
                raw={"vtable": t_old.vtable},
            ),
            after=EntitySnapshot(
                entity_repr=f"vtable={t_new.vtable}",
                raw={"vtable": t_new.vtable},
            ),
            severity=ChangeSeverity.BREAK,
            origin=Origin.CASTXML,
            confidence=0.9,
        ))

    return changes


def _diff_fields(t_old: RecordType, t_new: RecordType) -> list[Change]:
    changes: list[Change] = []
    old_fields = {f.name: f for f in t_old.fields}
    new_fields = {f.name: f for f in t_new.fields}

    # Removed fields
    for name in set(old_fields) - set(new_fields):
        changes.append(Change(
            change_kind=ChangeKind.TYPE_LAYOUT,
            entity_type="field",
            entity_name=f"{t_old.name}::{name}",
            before=EntitySnapshot(entity_repr=f"{old_fields[name].type} {name}"),
            after=EntitySnapshot(entity_repr="<removed>"),
            severity=ChangeSeverity.BREAK,
            origin=Origin.CASTXML,
            confidence=0.95,
        ))

    # Added fields
    for name in set(new_fields) - set(old_fields):
        changes.append(Change(
            change_kind=ChangeKind.TYPE_LAYOUT,
            entity_type="field",
            entity_name=f"{t_old.name}::{name}",
            before=EntitySnapshot(entity_repr="<absent>"),
            after=EntitySnapshot(entity_repr=f"{new_fields[name].type} {name}"),
            severity=ChangeSeverity.BREAK,
            origin=Origin.CASTXML,
            confidence=0.85,
        ))

    # Changed fields (offset or type change)
    for name in set(old_fields) & set(new_fields):
        f_old = old_fields[name]
        f_new = new_fields[name]
        if f_old.type != f_new.type or f_old.offset_bits != f_new.offset_bits:
            changes.append(Change(
                change_kind=ChangeKind.TYPE_LAYOUT,
                entity_type="field",
                entity_name=f"{t_old.name}::{name}",
                before=EntitySnapshot(
                    entity_repr=f"{f_old.type} {name} @{f_old.offset_bits}",
                    raw={"type": f_old.type, "offset_bits": f_old.offset_bits},
                ),
                after=EntitySnapshot(
                    entity_repr=f"{f_new.type} {name} @{f_new.offset_bits}",
                    raw={"type": f_new.type, "offset_bits": f_new.offset_bits},
                ),
                severity=ChangeSeverity.BREAK,
                origin=Origin.CASTXML,
                confidence=0.9,
            ))

    return changes


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def diff_type_layouts(
    before: NormalizedSnapshot,
    after: NormalizedSnapshot,
) -> list[Change]:
    """Two-phase type layout diff.

    Phase 1: hash filter — O(N) scan, build set of changed type names.
    Phase 2: deep diff — only for types with hash mismatches.

    Types only in before → removed (BREAK).
    Types only in after  → added (COMPATIBLE_EXTENSION).
    Types in both        → phase 1 hash check → phase 2 if changed.
    """
    changes: list[Change] = []

    before_types = before.type_index
    after_types = after.type_index

    # Removed types
    for name in set(before_types) - set(after_types):
        t = before_types[name]
        changes.append(Change(
            change_kind=ChangeKind.TYPE_LAYOUT,
            entity_type="type",
            entity_name=name,
            before=_type_snapshot(t),
            after=EntitySnapshot(entity_repr="<removed>"),
            severity=ChangeSeverity.BREAK,
            origin=Origin.CASTXML,
            confidence=0.9,
        ))

    # Added types
    for name in set(after_types) - set(before_types):
        t = after_types[name]
        changes.append(Change(
            change_kind=ChangeKind.TYPE_LAYOUT,
            entity_type="type",
            entity_name=name,
            before=EntitySnapshot(entity_repr="<absent>"),
            after=_type_snapshot(t),
            severity=ChangeSeverity.COMPATIBLE_EXTENSION,
            origin=Origin.CASTXML,
            confidence=0.9,
        ))

    # Changed types: phase 1 hash filter, then phase 2 deep diff
    before_hashes = {
        name: _type_structural_hash(t)
        for name, t in before_types.items()
        if name in after_types
    }
    for name in set(before_types) & set(after_types):
        t_old = before_types[name]
        t_new = after_types[name]
        h_old = before_hashes[name]
        h_new = _type_structural_hash(t_new)
        if h_old != h_new:
            changes.extend(_diff_type_pair(t_old, t_new))

    return changes
