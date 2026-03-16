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

"""Checker — diff two AbiSnapshots, classify changes, produce a verdict."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .checker_policy import (
    API_BREAK_KINDS as _API_BREAK_KINDS,
)
from .checker_policy import (
    BREAKING_KINDS as _BREAKING_KINDS,
)
from .checker_policy import (
    COMPATIBLE_KINDS as _COMPATIBLE_KINDS,
)
from .checker_policy import (
    RISK_KINDS as _RISK_KINDS,
)
from .checker_policy import (
    ChangeKind,
    Verdict,
    compute_verdict,
)
from .checker_policy import (
    policy_kind_sets as _policy_kind_sets,
)
from .detectors import DetectorResult
from .dwarf_advanced import diff_advanced_dwarf
from .elf_metadata import SymbolBinding, SymbolType
from .model import (
    AbiSnapshot,
    EnumType,
    Function,
    RecordType,
    TypeField,
    Variable,
    Visibility,
)

if TYPE_CHECKING:
    from .policy_file import PolicyFile
    from .suppression import SuppressionList

# Visibility levels that constitute the public ABI surface.
_PUBLIC_VIS = (Visibility.PUBLIC, Visibility.ELF_ONLY)


def _public_functions(snap: AbiSnapshot) -> dict[str, Function]:
    """Return public/ELF-only functions from *snap*."""
    return {k: v for k, v in snap.function_map.items() if v.visibility in _PUBLIC_VIS}


def _public_variables(snap: AbiSnapshot) -> dict[str, Variable]:
    """Return public/ELF-only variables from *snap*."""
    return {k: v for k, v in snap.variable_map.items() if v.visibility in _PUBLIC_VIS}


__all__ = [
    "ChangeKind",
    "Verdict",
    "_BREAKING_KINDS",
    "_COMPATIBLE_KINDS",
    "_API_BREAK_KINDS",
    "_RISK_KINDS",
    "_SOURCE_BREAK_KINDS",  # deprecated alias
    "Change",
    "LibraryMetadata",
    "DiffResult",
    "compare",
]

# Deprecated alias — kept for external consumers; will be removed in v2.0
_SOURCE_BREAK_KINDS = _API_BREAK_KINDS


@dataclass
class Change:
    kind: ChangeKind
    symbol: str               # mangled name or type name
    description: str          # human-readable
    old_value: str | None = None
    new_value: str | None = None
    source_location: str | None = None   # "header.h:42" if available
    affected_symbols: list[str] | None = None  # exported functions using this type


@dataclass
class LibraryMetadata:
    """File-level metadata for a library artifact (path, hash, size)."""
    path: str                     # file path as given on the CLI
    sha256: str                   # hex digest
    size_bytes: int               # file size in bytes


@dataclass
class DiffResult:
    old_version: str
    new_version: str
    library: str
    changes: list[Change] = field(default_factory=list)
    verdict: Verdict = Verdict.NO_CHANGE
    suppressed_count: int = 0
    suppressed_changes: list[Change] = field(default_factory=list)  # full audit trail
    suppression_file_provided: bool = False  # True when --suppress was passed, even if 0 matched
    detector_results: list[DetectorResult] = field(default_factory=list)
    policy: str = "strict_abi"  # active policy profile; drives breaking/source_breaks/compatible
    old_metadata: LibraryMetadata | None = None
    new_metadata: LibraryMetadata | None = None

    @property
    def breaking(self) -> list[Change]:
        """Changes classified as BREAKING under the active policy."""
        breaking_set, _, _, _ = _policy_kind_sets(self.policy)
        return [c for c in self.changes if c.kind in breaking_set]

    @property
    def source_breaks(self) -> list[Change]:
        """Changes classified as API_BREAK under the active policy."""
        _, api_break_set, _, _ = _policy_kind_sets(self.policy)
        return [c for c in self.changes if c.kind in api_break_set]

    @property
    def compatible(self) -> list[Change]:
        """Changes classified as COMPATIBLE under the active policy."""
        _, _, compatible_set, _ = _policy_kind_sets(self.policy)
        return [c for c in self.changes if c.kind in compatible_set]

    @property
    def risk(self) -> list[Change]:
        """Changes classified as COMPATIBLE_WITH_RISK under the active policy."""
        _, _, _, risk_set = _policy_kind_sets(self.policy)
        return [c for c in self.changes if c.kind in risk_set]


@dataclass(frozen=True)
class _DetectorSpec:
    name: str
    run: Callable[[AbiSnapshot, AbiSnapshot], list[Change]]
    is_supported: Callable[[AbiSnapshot, AbiSnapshot], tuple[bool, str | None]] | None = None

    def support(self, old: AbiSnapshot, new: AbiSnapshot) -> tuple[bool, str | None]:
        if self.is_supported is None:
            return True, None
        return self.is_supported(old, new)

def _check_removed_function(
    mangled: str, f_old: Function, new_all: dict[str, Function],
    elf_only_mode: bool,
) -> Change:
    """Create a Change for a function that was removed or hidden."""
    f_hidden = new_all.get(mangled)
    if (
        f_hidden is not None
        and f_hidden.visibility == Visibility.HIDDEN
        and not (elf_only_mode and f_old.visibility == Visibility.ELF_ONLY)
    ):
        return Change(
            kind=ChangeKind.FUNC_VISIBILITY_CHANGED,
            symbol=mangled,
            description=f"Function visibility changed to hidden: {f_old.name}",
            old_value=f_old.visibility.value,
            new_value=f_hidden.visibility.value,
        )
    removed_kind = (
        ChangeKind.FUNC_REMOVED_ELF_ONLY
        if (elf_only_mode and f_old.visibility == Visibility.ELF_ONLY)
        else ChangeKind.FUNC_REMOVED
    )
    return Change(
        kind=removed_kind,
        symbol=mangled,
        description=f"{f_old.visibility.value.capitalize()} function removed: {f_old.name}",
        old_value=f_old.name,
    )


def _check_function_signature(mangled: str, f_old: Function, f_new: Function) -> list[Change]:
    """Compare signatures and qualifiers of two matched functions."""
    changes: list[Change] = []

    if f_old.return_type != f_new.return_type:
        changes.append(Change(
            kind=ChangeKind.FUNC_RETURN_CHANGED,
            symbol=mangled,
            description=f"Return type changed: {f_old.name}",
            old_value=f_old.return_type,
            new_value=f_new.return_type,
        ))

    old_params = [(p.type, p.kind) for p in f_old.params]
    new_params = [(p.type, p.kind) for p in f_new.params]
    if old_params != new_params:
        changes.append(Change(
            kind=ChangeKind.FUNC_PARAMS_CHANGED,
            symbol=mangled,
            description=f"Parameters changed: {f_old.name}",
            old_value=str(old_params),
            new_value=str(new_params),
        ))

    if f_old.is_noexcept and not f_new.is_noexcept:
        changes.append(Change(
            kind=ChangeKind.FUNC_NOEXCEPT_REMOVED,
            symbol=mangled,
            description=f"noexcept specifier removed: {f_old.name}",
        ))
    elif not f_old.is_noexcept and f_new.is_noexcept:
        changes.append(Change(
            kind=ChangeKind.FUNC_NOEXCEPT_ADDED,
            symbol=mangled,
            description=f"noexcept specifier added: {f_old.name}",
        ))

    if not f_old.is_virtual and f_new.is_virtual:
        changes.append(Change(
            kind=ChangeKind.FUNC_VIRTUAL_ADDED,
            symbol=mangled,
            description=f"Function became virtual: {f_old.name}",
        ))
    elif f_old.is_virtual and not f_new.is_virtual:
        changes.append(Change(
            kind=ChangeKind.FUNC_VIRTUAL_REMOVED,
            symbol=mangled,
            description=f"Function is no longer virtual: {f_old.name}",
        ))

    return changes


def _check_inline_transitions(
    old_map: dict[str, Function], new_map: dict[str, Function],
    new_snapshot: AbiSnapshot,
) -> list[Change]:
    """Detect inline/non-inline transitions for functions present in both snapshots."""
    changes: list[Change] = []
    for mangled in set(old_map) & set(new_map):
        f_old = old_map[mangled]
        f_new = new_map[mangled]
        if not f_old.is_inline and f_new.is_inline:
            new_elf = new_snapshot.elf
            still_exported = (
                new_elf is not None
                and any(s.name == mangled for s in new_elf.symbols)
            )
            changes.append(Change(
                kind=ChangeKind.FUNC_BECAME_INLINE,
                symbol=mangled,
                description=(
                    f"Function became inline, symbol still exported: {f_old.name}"
                    if still_exported
                    else f"Function became inline (symbol may be removed from DSO): {f_old.name}"
                ),
                old_value="non-inline",
                new_value="inline",
            ))
        elif f_old.is_inline and not f_new.is_inline:
            changes.append(Change(
                kind=ChangeKind.FUNC_LOST_INLINE,
                symbol=mangled,
                description=f"Function lost inline attribute (now has external linkage): {f_old.name}",
                old_value="inline",
                new_value="non-inline",
            ))
    return changes


def _diff_functions(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    elf_only_mode = getattr(old, "elf_only_mode", False)
    changes: list[Change] = []
    old_map = {k: v for k, v in old.function_map.items() if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)}
    new_map = {k: v for k, v in new.function_map.items() if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)}

    # Build a lookup of ALL functions in new snapshot (including hidden).
    new_all = new.function_map

    for mangled, f_old in old_map.items():
        if mangled not in new_map:
            changes.append(_check_removed_function(mangled, f_old, new_all, elf_only_mode))
            continue
        changes.extend(_check_function_signature(mangled, f_old, new_map[mangled]))

    for mangled, f_new in new_map.items():
        if mangled not in old_map:
            changes.append(Change(
                kind=ChangeKind.FUNC_ADDED,
                symbol=mangled,
                description=f"New public function: {f_new.name}",
                new_value=f_new.name,
            ))

    # FUNC_DELETED: function was not deleted before, now marked = delete
    old_all = old.function_map
    new_all_map = new.function_map
    for mangled, f_new in new_all_map.items():
        if not f_new.is_deleted:
            continue
        f_old_any = old_all.get(mangled)
        if f_old_any is not None and not f_old_any.is_deleted:
            changes.append(Change(
                kind=ChangeKind.FUNC_DELETED,
                symbol=mangled,
                description=f"Function explicitly deleted (= delete): {f_new.name}",
                old_value="callable",
                new_value="deleted",
            ))

    # FUNC_BECAME_INLINE / FUNC_LOST_INLINE: detect inline↔non-inline transitions
    changes.extend(_check_inline_transitions(old_map, new_map, new))

    return changes


def _diff_variables(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    changes: list[Change] = []
    old_map = _public_variables(old)
    new_map = _public_variables(new)

    for mangled, v_old in old_map.items():
        if mangled not in new_map:
            changes.append(Change(
                kind=ChangeKind.VAR_REMOVED,
                symbol=mangled,
                description=f"Public variable removed: {v_old.name}",
            ))
        elif old_map[mangled].type != new_map[mangled].type:
            changes.append(Change(
                kind=ChangeKind.VAR_TYPE_CHANGED,
                symbol=mangled,
                description=f"Variable type changed: {v_old.name}",
                old_value=v_old.type, new_value=new_map[mangled].type,
            ))
        else:
            v_new = new_map[mangled]
            if not v_old.is_const and v_new.is_const:
                changes.append(Change(
                    kind=ChangeKind.VAR_BECAME_CONST,
                    symbol=mangled,
                    description=f"Variable became const-qualified: {v_old.name} (writes now → SIGSEGV)",
                    old_value="non-const",
                    new_value="const",
                ))
            elif v_old.is_const and not v_new.is_const:
                changes.append(Change(
                    kind=ChangeKind.VAR_LOST_CONST,
                    symbol=mangled,
                    description=f"Variable lost const qualifier: {v_old.name} (ODR / inlining break)",
                    old_value="const",
                    new_value="non-const",
                ))

    for mangled, v_new in new_map.items():
        if mangled not in old_map:
            changes.append(Change(
                kind=ChangeKind.VAR_ADDED,
                symbol=mangled,
                description=f"New public variable: {v_new.name}",
            ))
    return changes


def _diff_types(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    changes: list[Change] = []
    # Include ALL types (including unions) for size/alignment/base/vtable checks.
    # TYPE_FIELD_* for unions is skipped below — handled by _diff_unions() instead.
    old_map = {t.name: t for t in old.types}
    new_map = {t.name: t for t in new.types}

    for name, t_old in old_map.items():
        t_new = new_map.get(name)
        if t_new is None:
            changes.append(Change(
                kind=ChangeKind.TYPE_REMOVED,
                symbol=name,
                description=f"Type removed: {name}",
            ))
            continue
        changes.extend(_diff_type_pair(name, t_old, t_new))

    for name in new_map:
        if name not in old_map:
            changes.append(Change(
                kind=ChangeKind.TYPE_ADDED,
                symbol=name,
                description=f"New type: {name}",
            ))

    return changes


def _diff_type_pair(name: str, t_old: RecordType, t_new: RecordType) -> list[Change]:
    changes: list[Change] = []

    # TYPE_BECAME_OPAQUE: was complete, now forward-decl only
    if not t_old.is_opaque and t_new.is_opaque:
        changes.append(Change(
            kind=ChangeKind.TYPE_BECAME_OPAQUE,
            symbol=name,
            description=f"Type became opaque (forward-declaration only): {name} — stack allocation no longer possible",
            old_value="complete",
            new_value="opaque",
        ))
        return changes  # no further checks meaningful for opaque type

    _append_type_size_and_alignment_changes(changes, name, t_old, t_new)
    if not t_old.is_union:
        changes.extend(_diff_type_fields(name, t_old, t_new))
    changes.extend(_diff_type_bases(name, t_old, t_new))
    changes.extend(_diff_type_vtable(name, t_old, t_new))
    return changes


def _append_type_size_and_alignment_changes(
    changes: list[Change], name: str, t_old: RecordType, t_new: RecordType,
) -> None:
    if t_old.size_bits is not None and t_new.size_bits is not None and t_old.size_bits != t_new.size_bits:
        changes.append(Change(
            kind=ChangeKind.TYPE_SIZE_CHANGED,
            symbol=name,
            description=f"Size changed: {name} ({t_old.size_bits} → {t_new.size_bits} bits)",
            old_value=str(t_old.size_bits),
            new_value=str(t_new.size_bits),
        ))

    if (
        t_old.alignment_bits is not None
        and t_new.alignment_bits is not None
        and t_old.alignment_bits != t_new.alignment_bits
    ):
        changes.append(Change(
            kind=ChangeKind.TYPE_ALIGNMENT_CHANGED,
            symbol=name,
            description=f"Alignment changed: {name} ({t_old.alignment_bits} → {t_new.alignment_bits} bits)",
            old_value=str(t_old.alignment_bits),
            new_value=str(t_new.alignment_bits),
        ))


def _diff_type_fields(name: str, t_old: RecordType, t_new: RecordType) -> list[Change]:
    changes: list[Change] = []
    old_fields = {f.name: f for f in t_old.fields}
    new_fields = {f.name: f for f in t_new.fields}

    for fname, f_old in old_fields.items():
        f_new = new_fields.get(fname)
        if f_new is None:
            changes.append(Change(
                kind=ChangeKind.TYPE_FIELD_REMOVED,
                symbol=name,
                description=f"Field removed: {name}::{fname}",
            ))
            continue
        changes.extend(_diff_type_field_pair(name, fname, f_old, f_new))

    for fname in new_fields:
        if fname not in old_fields:
            changes.append(Change(
                kind=_new_field_change_kind(t_new),
                symbol=name,
                description=f"Field added: {name}::{fname}",
            ))
    return changes


def _diff_type_field_pair(name: str, fname: str, f_old: TypeField, f_new: TypeField) -> list[Change]:
    changes: list[Change] = []
    if f_old.type != f_new.type:
        changes.append(Change(
            kind=ChangeKind.TYPE_FIELD_TYPE_CHANGED,
            symbol=name,
            description=f"Field type changed: {name}::{fname}",
            old_value=f_old.type,
            new_value=f_new.type,
        ))
    if f_old.offset_bits is not None and f_new.offset_bits is not None and f_old.offset_bits != f_new.offset_bits:
        changes.append(Change(
            kind=ChangeKind.TYPE_FIELD_OFFSET_CHANGED,
            symbol=name,
            description=f"Field offset changed: {name}::{fname} ({f_old.offset_bits} → {f_new.offset_bits} bits)",
            old_value=str(f_old.offset_bits),
            new_value=str(f_new.offset_bits),
        ))
    if f_old.is_bitfield != f_new.is_bitfield or f_old.bitfield_bits != f_new.bitfield_bits:
        changes.append(Change(
            kind=ChangeKind.FIELD_BITFIELD_CHANGED,
            symbol=name,
            description=f"Bitfield layout changed: {name}::{fname}",
            old_value=f"bits={f_old.bitfield_bits}",
            new_value=f"bits={f_new.bitfield_bits}",
        ))
    return changes


def _new_field_change_kind(t_new: RecordType) -> ChangeKind:
    # Field addition is BREAKING for polymorphic types or types with vtables;
    # COMPATIBLE only for standard-layout types without virtual functions.
    is_polymorphic = bool(t_new.vtable or t_new.virtual_bases)
    return (
        ChangeKind.TYPE_FIELD_ADDED_COMPATIBLE
        if not is_polymorphic and t_new.kind == "struct"
        else ChangeKind.TYPE_FIELD_ADDED
    )


def _diff_type_bases(name: str, t_old: RecordType, t_new: RecordType) -> list[Change]:
    changes: list[Change] = []

    # BASE_CLASS_POSITION_CHANGED: same set of non-virtual bases, different order
    # This shifts this-pointer adjustments for all bases → old binaries call wrong method.
    old_bases_set = set(t_old.bases)
    new_bases_set = set(t_new.bases)
    if old_bases_set == new_bases_set and t_old.bases != t_new.bases:
        changes.append(Change(
            kind=ChangeKind.BASE_CLASS_POSITION_CHANGED,
            symbol=name,
            description=f"Base class order reordered: {name} — this-pointer adjustments changed",
            old_value=str(t_old.bases),
            new_value=str(t_new.bases),
        ))
    elif old_bases_set != new_bases_set:
        # General base class set change (add/remove base) → TYPE_BASE_CHANGED
        changes.append(Change(
            kind=ChangeKind.TYPE_BASE_CHANGED,
            symbol=name,
            description=f"Base classes changed: {name}",
            old_value=str(t_old.bases),
            new_value=str(t_new.bases),
        ))

    # BASE_CLASS_VIRTUAL_CHANGED: a base moved between virtual and non-virtual
    old_virt_set = set(t_old.virtual_bases)
    new_virt_set = set(t_new.virtual_bases)
    # Bases that moved from non-virtual to virtual or vice versa
    became_virtual = (new_virt_set - old_virt_set) & old_bases_set
    lost_virtual = (old_virt_set - new_virt_set) & new_bases_set
    if became_virtual or lost_virtual:
        desc_parts = []
        if became_virtual:
            desc_parts.append(f"became virtual: {sorted(became_virtual)}")
        if lost_virtual:
            desc_parts.append(f"lost virtual: {sorted(lost_virtual)}")
        changes.append(Change(
            kind=ChangeKind.BASE_CLASS_VIRTUAL_CHANGED,
            symbol=name,
            description=f"Base class virtual inheritance changed: {name} — {'; '.join(desc_parts)}",
            old_value=str(sorted(t_old.virtual_bases)),
            new_value=str(sorted(t_new.virtual_bases)),
        ))
    elif old_virt_set != new_virt_set:
        # Pure add/remove of a virtual base (not a migration from non-virtual):
        # e.g. class D : virtual A  →  class D : virtual A, virtual B
        # → TYPE_BASE_CHANGED (hierarchy changed, not just virtuality toggled)
        if not changes:  # don't duplicate if TYPE_BASE_CHANGED already emitted above
            changes.append(Change(
                kind=ChangeKind.TYPE_BASE_CHANGED,
                symbol=name,
                description=f"Virtual base classes changed: {name}",
                old_value=str(t_old.virtual_bases),
                new_value=str(t_new.virtual_bases),
            ))

    return changes


def _diff_type_vtable(name: str, t_old: RecordType, t_new: RecordType) -> list[Change]:
    if t_old.vtable == t_new.vtable:
        return []
    description = (
        f"vtable reordered: {name}"
        if Counter(t_old.vtable) == Counter(t_new.vtable)
        else f"vtable changed: {name}"
    )
    return [Change(
        kind=ChangeKind.TYPE_VTABLE_CHANGED,
        symbol=name,
        description=description,
        old_value=", ".join(t_old.vtable),
        new_value=", ".join(t_new.vtable),
    )]


def _diff_enums(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    changes: list[Change] = []
    old_map: dict[str, EnumType] = {e.name: e for e in old.enums}
    new_map: dict[str, EnumType] = {e.name: e for e in new.enums}

    for name, e_old in old_map.items():
        if name not in new_map:
            continue  # TYPE_REMOVED covers this
        e_new = new_map[name]
        old_members = {m.name: m.value for m in e_old.members}
        new_members = {m.name: m.value for m in e_new.members}
        # "Sentinel" member = member with the highest integer value in old enum.
        # Detecting its value change is important (e.g. FOO_MAX / FOO_COUNT patterns).
        # Use max-value comparison, NOT list-position order (castxml order is unreliable).
        old_max_val = max(old_members.values()) if old_members else None
        old_sentinel = (
            next(n for n, v in old_members.items() if v == old_max_val)
            if old_max_val is not None else None
        )

        # Build inverse map: new_value → new_name for values that are "new" (not in old names)
        # If a missing old member value still exists under a different new name,
        # it is a rename, not a true removal. The separate rename detector emits
        # ENUM_MEMBER_RENAMED; we should not emit ENUM_MEMBER_REMOVED here.
        new_val_to_newname = {
            nval: nname for nname, nval in new_members.items()
            if nname not in old_members
        }

        for mname, mval in old_members.items():
            if mname not in new_members:
                # rename-only -> skip removed emission
                if mval in new_val_to_newname:
                    continue
                # Value truly removed
                changes.append(Change(
                    kind=ChangeKind.ENUM_MEMBER_REMOVED,
                    symbol=name,
                    description=f"Enum member removed: {name}::{mname}",
                    old_value=str(mval),
                ))
            elif new_members[mname] != mval:
                kind = (
                    ChangeKind.ENUM_LAST_MEMBER_VALUE_CHANGED
                    if mname == old_sentinel
                    else ChangeKind.ENUM_MEMBER_VALUE_CHANGED
                )
                changes.append(Change(
                    kind=kind,
                    symbol=name,
                    description=f"Enum member value changed: {name}::{mname}",
                    old_value=str(mval),
                    new_value=str(new_members[mname]),
                ))

        # Skip additions whose values exist in the old enum:
        # those will be handled as ENUM_MEMBER_RENAMED by _diff_enum_renames,
        # Skip additions whose value matches a removed old member (likely a rename).
        # Use only *removed* old member values — if the old member still exists under
        # the same name, the new member is a genuine addition (alias/duplicate), not
        # a rename, and must be reported. (CodeRabbit P1: one-to-one guard)
        removed_old_values = {
            str(v) for mname, v in old_members.items()
            if mname not in new_members
        }
        for mname, mval in new_members.items():
            if mname not in old_members:
                if str(mval) in removed_old_values:
                    continue  # same value as a removed old member — rename candidate
                changes.append(Change(
                    kind=ChangeKind.ENUM_MEMBER_ADDED,
                    symbol=name,
                    description=f"Enum member added: {name}::{mname}",
                    new_value=str(mval),
                ))

    return changes


def _sig_key(f: Function) -> tuple[str, tuple[str, ...]]:
    """Normalized match key: (function_name, param_types).

    cv-qualifiers (const/volatile on `this`) and static-ness are NOT encoded in
    the mangled name lookup table, so we use the unqualified name + params tuple
    to find matching pairs across qualifier changes.
    """
    return (f.name, tuple(p.type for p in f.params))


def _diff_method_qualifiers(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect cv-qualifier, static, and pure-virtual changes.

    NOTE: Changing const/volatile/static causes the mangled symbol name to
    change (e.g. Foo::bar() const → _ZNK3Foo3barEv vs _ZN3Foo3barEv).  We
    therefore match functions by (name, param_types) rather than mangled name
    to find cross-qualifier pairs in the removed/added sets.
    """
    changes: list[Change] = []
    old_by_mangled = _public_functions(old)
    new_by_mangled = _public_functions(new)

    # --- Same-mangled checks: pure_virtual and is_static don't change mangling ---
    # is_static: Itanium ABI does NOT encode static-ness in the mangled name
    # (void Widget::bar() and static void Widget::bar() share the same mangled symbol).
    # is_pure_virtual: pure_virtual is not part of the mangled name either.
    for mangled, f_old in old_by_mangled.items():
        if mangled not in new_by_mangled:
            continue
        f_new = new_by_mangled[mangled]

        if f_old.is_static != f_new.is_static:
            changes.append(Change(
                kind=ChangeKind.FUNC_STATIC_CHANGED,
                symbol=mangled,
                description=f"Static qualifier changed: {f_old.name}",
                old_value=str(f_old.is_static),
                new_value=str(f_new.is_static),
            ))

        if not f_old.is_pure_virtual and f_new.is_pure_virtual:
            kind = (
                ChangeKind.FUNC_VIRTUAL_BECAME_PURE
                if f_old.is_virtual
                else ChangeKind.FUNC_PURE_VIRTUAL_ADDED
            )
            changes.append(Change(
                kind=kind,
                symbol=mangled,
                description=f"Function became pure virtual: {f_old.name}",
            ))

    # --- cv/static detection: match removed functions against added functions by sig ---
    old_mangles = set(old_by_mangled)
    new_mangles = set(new_by_mangled)
    removed_funcs = [old_by_mangled[m] for m in (old_mangles - new_mangles)]
    added_funcs = [new_by_mangled[m] for m in (new_mangles - old_mangles)]

    # Build sig-keyed lookup over newly-added functions
    added_by_sig: dict[tuple[str, tuple[str, ...]], Function] = {}
    for f in added_funcs:
        added_by_sig[_sig_key(f)] = f

    for f_old in removed_funcs:
        key = _sig_key(f_old)
        if key not in added_by_sig:
            continue
        f_new = added_by_sig[key]
        # Same (name, params) — only qualifiers changed; report instead of REMOVED+ADDED
        if f_old.is_static != f_new.is_static:
            changes.append(Change(
                kind=ChangeKind.FUNC_STATIC_CHANGED,
                symbol=f_old.mangled,
                description=f"Static qualifier changed: {f_old.name}",
                old_value=str(f_old.is_static),
                new_value=str(f_new.is_static),
            ))
        if f_old.is_const != f_new.is_const or f_old.is_volatile != f_new.is_volatile:
            changes.append(Change(
                kind=ChangeKind.FUNC_CV_CHANGED,
                symbol=f_old.mangled,
                description=f"CV qualifier changed: {f_old.name}",
                old_value=f"const={f_old.is_const} volatile={f_old.is_volatile}",
                new_value=f"const={f_new.is_const} volatile={f_new.is_volatile}",
            ))

    return changes


def _diff_unions(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    changes: list[Change] = []
    old_unions = {t.name: t for t in old.types if t.is_union}
    new_unions = {t.name: t for t in new.types if t.is_union}

    for name, t_old in old_unions.items():
        if name not in new_unions:
            continue  # covered by TYPE_REMOVED
        t_new = new_unions[name]
        old_fields = {f.name: f for f in t_old.fields}
        new_fields = {f.name: f for f in t_new.fields}

        for fname, f_old in old_fields.items():
            if fname not in new_fields:
                changes.append(Change(
                    kind=ChangeKind.UNION_FIELD_REMOVED,
                    symbol=name,
                    description=f"Union field removed: {name}::{fname}",
                    old_value=f_old.type,
                ))
            elif f_old.type != new_fields[fname].type:
                changes.append(Change(
                    kind=ChangeKind.UNION_FIELD_TYPE_CHANGED,
                    symbol=name,
                    description=f"Union field type changed: {name}::{fname}",
                    old_value=f_old.type,
                    new_value=new_fields[fname].type,
                ))

        for fname, f_new in new_fields.items():
            if fname not in old_fields:
                changes.append(Change(
                    kind=ChangeKind.UNION_FIELD_ADDED,
                    symbol=name,
                    description=f"Union field added: {name}::{fname}",
                    new_value=f_new.type,
                ))

    return changes


_VERSION_STAMPED_TYPEDEF_RE = re.compile(r"^(.*?)_version_\d+_\d+_\d+$", re.IGNORECASE)
"""Pattern for version-stamped compile-time sentinel typedefs.

Some libraries (e.g. libpng) define typedefs whose names encode the library
version, e.g. ``typedef char* png_libpng_version_1_6_46``.  The name changes
every release by design — this is NOT a binary ABI break because the typedef
is never exported as an ELF symbol; it exists solely to produce a
compile-time error if headers from different versions are mixed.

When such a typedef disappears (``typedef_removed``), abicheck would
otherwise report BREAKING.  This guard downgrades the change to
TYPEDEF_VERSION_SENTINEL (COMPATIBLE) instead.
"""


def _is_version_stamped_typedef(name: str) -> bool:
    """Return True if *name* looks like a version-stamped sentinel typedef."""
    return bool(_VERSION_STAMPED_TYPEDEF_RE.match(name))


def _has_version_family_successor(name: str, new_typedefs: dict[str, str]) -> bool:
    """Return True if *new_typedefs* contains another version-stamped typedef
    with the same family prefix (e.g. ``png_libpng_version_``).

    This distinguishes a sentinel rotation (old version removed, new version
    added) from a genuine typedef removal where the name happens to match the
    version-stamp pattern.
    """
    m = _VERSION_STAMPED_TYPEDEF_RE.match(name)
    if not m:
        return False
    prefix = m.group(1).lower()
    # Require a non-empty family prefix to avoid matching unrelated sentinels
    # when the name itself starts with _version_ (e.g. ``_version_1_0_0``).
    if not prefix:
        return False
    prefix = prefix + "_version_"
    return any(k.lower().startswith(prefix) for k in new_typedefs)


def _diff_typedefs(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    changes: list[Change] = []
    for alias, old_type in old.typedefs.items():
        new_type = new.typedefs.get(alias)
        if new_type is None:
            # Version-stamped typedefs (e.g. png_libpng_version_1_6_46) are
            # compile-time sentinels — their name encodes the version and
            # changes every release intentionally.  They are never exported as
            # ELF symbols, so their removal is NOT a binary ABI break.
            # Require a same-family successor in new_typedefs to avoid hiding
            # genuine TYPEDEF_REMOVED breaks for names that merely match the
            # version-stamp pattern.
            if _is_version_stamped_typedef(alias) and _has_version_family_successor(alias, new.typedefs):
                changes.append(Change(
                    kind=ChangeKind.TYPEDEF_VERSION_SENTINEL,
                    symbol=alias,
                    description=(
                        f"Version-stamped typedef removed (compile-time sentinel, "
                        f"not an ABI break): {alias}"
                    ),
                    old_value=old_type,
                ))
                continue
            # Typedef removed — breaking for consumers that used the alias
            changes.append(Change(
                kind=ChangeKind.TYPEDEF_REMOVED,
                symbol=alias,
                description=f"Typedef removed: {alias}",
                old_value=old_type,
            ))
        elif new_type != old_type:
            changes.append(Change(
                kind=ChangeKind.TYPEDEF_BASE_CHANGED,
                symbol=alias,
                description=f"Typedef base type changed: {alias}",
                old_value=old_type,
                new_value=new_type,
            ))
    return changes



# ── Sprint 7: enum rename, field qualifier, pointer level, access, param default ─


def _diff_enum_renames(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect enum member renames: same value present under different name."""
    changes: list[Change] = []
    old_map: dict[str, EnumType] = {e.name: e for e in old.enums}
    new_map: dict[str, EnumType] = {e.name: e for e in new.enums}

    for name, e_old in old_map.items():
        if name not in new_map:
            continue
        e_new = new_map[name]
        old_by_name = {m.name: m.value for m in e_old.members}
        new_by_name = {m.name: m.value for m in e_new.members}
        new_by_val: dict[int, str] = {m.value: m.name for m in e_new.members}

        for old_mname, old_mval in old_by_name.items():
            if old_mname in new_by_name:
                continue  # still present by name
            # Name gone — check if the value still exists under a new name
            if old_mval in new_by_val:
                new_mname = new_by_val[old_mval]
                if new_mname not in old_by_name:
                    changes.append(Change(
                        kind=ChangeKind.ENUM_MEMBER_RENAMED,
                        symbol=name,
                        description=f"Enum member renamed: {name}::{old_mname} → {new_mname} (value={old_mval})",
                        old_value=old_mname,
                        new_value=new_mname,
                    ))

    return changes


def _check_field_qualifier_pair(
    name: str, fname: str, f_old: TypeField, f_new: TypeField,
) -> list[Change]:
    """Check const/volatile/mutable qualifier changes for a single field pair."""
    changes: list[Change] = []

    if not f_old.is_const and f_new.is_const:
        changes.append(Change(
            kind=ChangeKind.FIELD_BECAME_CONST,
            symbol=name,
            description=f"Field became const: {name}::{fname}",
            old_value="non-const",
            new_value="const",
        ))
    elif f_old.is_const and not f_new.is_const:
        changes.append(Change(
            kind=ChangeKind.FIELD_LOST_CONST,
            symbol=name,
            description=f"Field lost const: {name}::{fname}",
            old_value="const",
            new_value="non-const",
        ))

    if not f_old.is_volatile and f_new.is_volatile:
        changes.append(Change(
            kind=ChangeKind.FIELD_BECAME_VOLATILE,
            symbol=name,
            description=f"Field became volatile: {name}::{fname}",
            old_value="non-volatile",
            new_value="volatile",
        ))
    elif f_old.is_volatile and not f_new.is_volatile:
        changes.append(Change(
            kind=ChangeKind.FIELD_LOST_VOLATILE,
            symbol=name,
            description=f"Field lost volatile: {name}::{fname}",
            old_value="volatile",
            new_value="non-volatile",
        ))

    if not f_old.is_mutable and f_new.is_mutable:
        changes.append(Change(
            kind=ChangeKind.FIELD_BECAME_MUTABLE,
            symbol=name,
            description=f"Field became mutable: {name}::{fname}",
            old_value="non-mutable",
            new_value="mutable",
        ))
    elif f_old.is_mutable and not f_new.is_mutable:
        changes.append(Change(
            kind=ChangeKind.FIELD_LOST_MUTABLE,
            symbol=name,
            description=f"Field lost mutable: {name}::{fname}",
            old_value="mutable",
            new_value="non-mutable",
        ))

    return changes


def _diff_field_qualifiers(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect field-level const/volatile/mutable qualifier changes."""
    changes: list[Change] = []
    old_map = {t.name: t for t in old.types if not t.is_union}
    new_map = {t.name: t for t in new.types if not t.is_union}

    for name, t_old in old_map.items():
        t_new = new_map.get(name)
        if t_new is None:
            continue
        old_fields = {f.name: f for f in t_old.fields}
        new_fields = {f.name: f for f in t_new.fields}

        for fname, f_old in old_fields.items():
            f_new = new_fields.get(fname)
            if f_new is None:
                continue
            changes.extend(_check_field_qualifier_pair(name, fname, f_old, f_new))

    return changes


def _diff_field_renames(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect field renames: same offset+type, different name."""
    changes: list[Change] = []
    old_map = {t.name: t for t in old.types if not t.is_union}
    new_map = {t.name: t for t in new.types if not t.is_union}

    for name, t_old in old_map.items():
        t_new = new_map.get(name)
        if t_new is None or t_new.is_opaque:
            continue
        old_names = {f.name for f in t_old.fields}
        new_names = {f.name for f in t_new.fields}

        removed = [f for f in t_old.fields if f.name not in new_names]
        added = [f for f in t_new.fields if f.name not in old_names]

        # Match by (offset, type) — a rename is when the same slot has a different name
        added_by_sig = {(f.offset_bits, f.type): f for f in added if f.offset_bits is not None}
        for f_old in removed:
            if f_old.offset_bits is None:
                continue
            sig = (f_old.offset_bits, f_old.type)
            f_new = added_by_sig.get(sig)
            if f_new is not None:
                changes.append(Change(
                    kind=ChangeKind.FIELD_RENAMED,
                    symbol=name,
                    description=f"Field renamed: {name}::{f_old.name} → {f_new.name}",
                    old_value=f_old.name,
                    new_value=f_new.name,
                ))

    return changes


def _diff_param_defaults(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect parameter default value changes/removals."""
    changes: list[Change] = []
    old_map = _public_functions(old)
    new_map = _public_functions(new)

    for mangled, f_old in old_map.items():
        f_new = new_map.get(mangled)
        if f_new is None:
            continue
        # Compare parameter defaults pairwise
        for i, (p_old, p_new) in enumerate(zip(f_old.params, f_new.params)):
            if p_old.default is not None and p_new.default is None:
                changes.append(Change(
                    kind=ChangeKind.PARAM_DEFAULT_VALUE_REMOVED,
                    symbol=mangled,
                    description=f"Parameter default removed: {f_old.name} param {p_old.name or i}",
                    old_value=p_old.default,
                    new_value=None,
                ))
            elif p_old.default is not None and p_new.default is not None and p_old.default != p_new.default:
                changes.append(Change(
                    kind=ChangeKind.PARAM_DEFAULT_VALUE_CHANGED,
                    symbol=mangled,
                    description=f"Parameter default changed: {f_old.name} param {p_old.name or i}",
                    old_value=p_old.default,
                    new_value=p_new.default,
                ))

    return changes


def _diff_param_renames(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect parameter renames (same type+position, different name)."""
    changes: list[Change] = []
    old_map = _public_functions(old)
    new_map = _public_functions(new)

    for mangled, f_old in old_map.items():
        f_new = new_map.get(mangled)
        if f_new is None:
            continue
        for i, (p_old, p_new) in enumerate(zip(f_old.params, f_new.params)):
            if p_old.type == p_new.type and p_old.name and p_new.name and p_old.name != p_new.name:
                changes.append(Change(
                    kind=ChangeKind.PARAM_RENAMED,
                    symbol=mangled,
                    description=f"Parameter renamed: {f_old.name} param {i}: {p_old.name} → {p_new.name}",
                    old_value=p_old.name,
                    new_value=p_new.name,
                ))

    return changes


def _diff_pointer_levels(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect pointer level changes in params and return types."""
    changes: list[Change] = []
    old_map = _public_functions(old)
    new_map = _public_functions(new)

    for mangled, f_old in old_map.items():
        f_new = new_map.get(mangled)
        if f_new is None:
            continue

        # Return pointer depth
        if f_old.return_pointer_depth != f_new.return_pointer_depth and (
            f_old.return_pointer_depth > 0 or f_new.return_pointer_depth > 0
        ):
            changes.append(Change(
                kind=ChangeKind.RETURN_POINTER_LEVEL_CHANGED,
                symbol=mangled,
                description=f"Return pointer level changed: {f_old.name} (depth {f_old.return_pointer_depth} → {f_new.return_pointer_depth})",
                old_value=str(f_old.return_pointer_depth),
                new_value=str(f_new.return_pointer_depth),
            ))

        # Param pointer depths
        for i, (p_old, p_new) in enumerate(zip(f_old.params, f_new.params)):
            if p_old.pointer_depth != p_new.pointer_depth and (
                p_old.pointer_depth > 0 or p_new.pointer_depth > 0
            ):
                changes.append(Change(
                    kind=ChangeKind.PARAM_POINTER_LEVEL_CHANGED,
                    symbol=mangled,
                    description=f"Parameter pointer level changed: {f_old.name} param {p_old.name or i} (depth {p_old.pointer_depth} → {p_new.pointer_depth})",
                    old_value=str(p_old.pointer_depth),
                    new_value=str(p_new.pointer_depth),
                ))

    return changes


def _is_access_narrowing(old_access: Any, new_access: Any) -> bool:
    """Return True if the access level transition is narrowing (breaking).

    Narrowing = less accessible: public→protected, public→private, protected→private.
    Widening (e.g., private→public) is backward-compatible and should NOT be flagged.
    """
    from .model import AccessLevel
    _RANK = {AccessLevel.PUBLIC: 0, AccessLevel.PROTECTED: 1, AccessLevel.PRIVATE: 2}  # pylint: disable=invalid-name
    return _RANK.get(new_access, 0) > _RANK.get(old_access, 0)


def _diff_access_levels(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect narrowing access level changes on methods and fields.

    Only flags narrowing transitions (public→protected/private, protected→private).
    Widening (e.g., private→public) is backward-compatible and not reported.
    """
    changes: list[Change] = []

    # Method access changes (narrowing only)
    old_map = _public_functions(old)
    new_map = _public_functions(new)

    for mangled, f_old in old_map.items():
        f_new = new_map.get(mangled)
        if f_new is None:
            continue
        if f_old.access != f_new.access and _is_access_narrowing(f_old.access, f_new.access):
            changes.append(Change(
                kind=ChangeKind.METHOD_ACCESS_CHANGED,
                symbol=mangled,
                description=f"Method access level narrowed: {f_old.name} ({f_old.access.value} → {f_new.access.value})",
                old_value=f_old.access.value,
                new_value=f_new.access.value,
            ))

    # Field access changes (narrowing only)
    old_types = {t.name: t for t in old.types if not t.is_union}
    new_types = {t.name: t for t in new.types if not t.is_union}

    for name, t_old in old_types.items():
        t_new = new_types.get(name)
        if t_new is None:
            continue
        old_fields = {f.name: f for f in t_old.fields}
        new_fields = {f.name: f for f in t_new.fields}

        for fname, f_old_f in old_fields.items():
            f_new_f = new_fields.get(fname)
            if f_new_f is None:
                continue
            if f_old_f.access != f_new_f.access and _is_access_narrowing(f_old_f.access, f_new_f.access):
                changes.append(Change(
                    kind=ChangeKind.FIELD_ACCESS_CHANGED,
                    symbol=name,
                    description=f"Field access level narrowed: {name}::{fname} ({f_old_f.access.value} → {f_new_f.access.value})",
                    old_value=f_old_f.access.value,
                    new_value=f_new_f.access.value,
                ))

    return changes


def _diff_anon_fields(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect changes in anonymous struct/union members."""
    changes: list[Change] = []
    old_map = {t.name: t for t in old.types}
    new_map = {t.name: t for t in new.types}

    for name, t_old in old_map.items():
        t_new = new_map.get(name)
        if t_new is None:
            continue
        # Look for fields with empty/anonymous names (compiler-generated)
        old_anon = [f for f in t_old.fields if not f.name or f.name.startswith("__anon")]
        new_anon = [f for f in t_new.fields if not f.name or f.name.startswith("__anon")]

        if not old_anon and not new_anon:
            continue

        # Compare anonymous fields by offset
        old_by_offset = {f.offset_bits: f for f in old_anon if f.offset_bits is not None}
        new_by_offset = {f.offset_bits: f for f in new_anon if f.offset_bits is not None}

        for offset, f_old in old_by_offset.items():
            f_new = new_by_offset.get(offset)
            if f_new is None:
                changes.append(Change(
                    kind=ChangeKind.ANON_FIELD_CHANGED,
                    symbol=name,
                    description=f"Anonymous field removed at offset {offset} in {name}",
                    old_value=f_old.type,
                ))
            elif f_old.type != f_new.type:
                changes.append(Change(
                    kind=ChangeKind.ANON_FIELD_CHANGED,
                    symbol=name,
                    description=f"Anonymous field type changed at offset {offset} in {name}",
                    old_value=f_old.type,
                    new_value=f_new.type,
                ))

    return changes


def _diff_elf(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """ELF-only detectors (Sprint 2): no debug info required."""
    from .elf_metadata import ElfMetadata

    o: ElfMetadata = getattr(old, "elf", None) or ElfMetadata()
    n: ElfMetadata = getattr(new, "elf", None) or ElfMetadata()
    changes: list[Change] = []
    changes.extend(_diff_elf_dynamic_section(o, n))
    changes.extend(_diff_elf_symbol_versioning(o, n))
    changes.extend(_diff_elf_symbol_metadata(o, n))
    changes.extend(_diff_visibility_leak(old, new))
    changes.extend(_diff_leaked_dependency_symbols(o, n))
    return changes


def _diff_pe(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """PE-specific detectors for Windows DLL ABI changes."""
    from .pe_metadata import PeMetadata

    o: PeMetadata = getattr(old, "pe", None) or PeMetadata()
    n: PeMetadata = getattr(new, "pe", None) or PeMetadata()
    changes: list[Change] = []

    # Export deltas from PE metadata can overlap with _diff_functions() when
    # the same symbols are present in snapshot.functions. Keep PE signal, but
    # deduplicate per symbol so we don't double-report while still preserving
    # metadata-only changes that function model may miss.
    old_ids = {(e.name if e.name else f"ordinal:{e.ordinal}") for e in o.exports}
    new_ids = {(e.name if e.name else f"ordinal:{e.ordinal}") for e in n.exports}
    old_fn_names = {f.name for f in old.functions if f.name}
    new_fn_names = {f.name for f in new.functions if f.name}

    removed_kind = (
        ChangeKind.FUNC_REMOVED_ELF_ONLY
        if getattr(old, "elf_only_mode", False) and getattr(new, "elf_only_mode", False)
        else ChangeKind.FUNC_REMOVED
    )
    for eid in sorted(old_ids - new_ids):
        if eid in old_fn_names:
            continue
        changes.append(Change(
            kind=removed_kind,
            symbol=eid,
            description=f"export removed from DLL: {eid}",
        ))

    for eid in sorted(new_ids - old_ids):
        if eid in new_fn_names:
            continue
        changes.append(Change(
            kind=ChangeKind.FUNC_ADDED,
            symbol=eid,
            description=f"new export in DLL: {eid}",
        ))

    # Detect changed import dependencies
    old_deps = set(o.imports.keys())
    new_deps = set(n.imports.keys())
    for dep in sorted(old_deps - new_deps):
        changes.append(Change(
            kind=ChangeKind.NEEDED_REMOVED,
            symbol=dep,
            description=f"import dependency removed: {dep}",
        ))
    for dep in sorted(new_deps - old_deps):
        changes.append(Change(
            kind=ChangeKind.NEEDED_ADDED,
            symbol=dep,
            description=f"new import dependency: {dep}",
        ))

    return changes


def _diff_macho(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Mach-O-specific detectors for macOS dylib ABI changes."""
    from .macho_metadata import MachoMetadata

    o: MachoMetadata = getattr(old, "macho", None) or MachoMetadata()
    n: MachoMetadata = getattr(new, "macho", None) or MachoMetadata()
    changes: list[Change] = []

    # Export deltas from Mach-O metadata can overlap with _diff_functions().
    # Deduplicate per symbol to avoid double-reporting, but keep metadata-only
    # changes that function model may miss.
    if o.exports or n.exports:
        old_names = {e.name for e in o.exports if e.name}
        new_names = {e.name for e in n.exports if e.name}
        old_fn_names = {f.name for f in old.functions if f.name}
        new_fn_names = {f.name for f in new.functions if f.name}

        removed_kind = (
            ChangeKind.FUNC_REMOVED_ELF_ONLY
            if getattr(old, "elf_only_mode", False) and getattr(new, "elf_only_mode", False)
            else ChangeKind.FUNC_REMOVED
        )
        for name in sorted(old_names - new_names):
            if name in old_fn_names:
                continue
            changes.append(Change(
                kind=removed_kind,
                symbol=name,
                description=f"export removed from dylib: {name}",
            ))

        for name in sorted(new_names - old_names):
            if name in new_fn_names:
                continue
            changes.append(Change(
                kind=ChangeKind.FUNC_ADDED,
                symbol=name,
                description=f"new export in dylib: {name}",
            ))

    # Install name change (equivalent of SONAME change)
    if o.install_name and o.install_name != n.install_name:
        changes.append(Change(
            kind=ChangeKind.SONAME_CHANGED,
            symbol="LC_ID_DYLIB",
            old_value=o.install_name,
            new_value=n.install_name,
            description=f"install name changed: {o.install_name} → {n.install_name}",
        ))

    # Compatibility version change (LC_ID_DYLIB compat_version — binary contract)
    if o.compat_version and o.compat_version != n.compat_version:
        changes.append(Change(
            kind=ChangeKind.COMPAT_VERSION_CHANGED,
            symbol="compat_version",
            old_value=o.compat_version,
            new_value=n.compat_version,
            description=f"compatibility version changed: {o.compat_version} → {n.compat_version}",
        ))

    # Detect dependency changes
    old_deps = set(o.dependent_libs)
    new_deps = set(n.dependent_libs)
    for dep in sorted(old_deps - new_deps):
        changes.append(Change(
            kind=ChangeKind.NEEDED_REMOVED,
            symbol=dep,
            description=f"dependency removed: {dep}",
        ))
    for dep in sorted(new_deps - old_deps):
        changes.append(Change(
            kind=ChangeKind.NEEDED_ADDED,
            symbol=dep,
            description=f"new dependency: {dep}",
        ))

    # Detect re-exported dylib changes (LC_REEXPORT_DYLIB)
    old_reexports = set(o.reexported_libs)
    new_reexports = set(n.reexported_libs)
    for lib in sorted(old_reexports - new_reexports):
        changes.append(Change(
            kind=ChangeKind.NEEDED_REMOVED,
            symbol=lib,
            description=f"re-exported dylib removed: {lib}",
        ))
    for lib in sorted(new_reexports - old_reexports):
        changes.append(Change(
            kind=ChangeKind.NEEDED_ADDED,
            symbol=lib,
            description=f"new re-exported dylib: {lib}",
        ))

    return changes




_INTERNAL_NAME_PATTERNS = (
    "internal",
    "helper",
    "_impl",
    "detail",
    "private",
    "__",
    "_priv",
    "_int_",
    "_do_",
    "_handle_",
)


def _looks_internal(name: str) -> bool:
    """Heuristic: True if symbol name looks like internal implementation detail."""
    lower = name.lower()
    return any(pat in lower for pat in _INTERNAL_NAME_PATTERNS)


def _diff_visibility_leak(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect old-library visibility leaks (ELF-only internal symbols exported)."""
    del new  # detector is intentionally old-library-only
    if not getattr(old, "elf_only_mode", False):
        return []

    leaked = [
        f for f in old.functions
        if f.visibility == Visibility.ELF_ONLY and _looks_internal(f.name)
    ]
    if not leaked:
        return []

    names = ", ".join(f.name for f in leaked[:5])
    suffix = f" (+{len(leaked) - 5} more)" if len(leaked) > 5 else ""
    return [Change(
        kind=ChangeKind.VISIBILITY_LEAK,
        symbol="<visibility>",
        description=(
            f"Old library exports {len(leaked)} internal-looking symbol(s) without "
            f"-fvisibility=hidden (bad practice — accidental ABI surface enlargement): "
            f"{names}{suffix}"
        ),
        old_value=str(len(leaked)),
    )]

def _diff_leaked_dependency_symbols(old_elf: Any, new_elf: Any) -> list[Change]:
    """Detect symbols that were added or removed and appear to originate from a dependency.

    When a symbol exported by this library was detected as likely originating from
    a dependency (libstdc++, libgcc, libc, …), any *addition* or *removal* of that
    symbol gets annotated as ``SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED``.

    Symbols that exist in both old and new with the same origin are intentionally
    **not** re-emitted here — ``_diff_elf_symbol_metadata`` already covers changes
    to the symbol's type/binding/size and emits its own Change records.  Emitting a
    second Change for the same symbol from both detectors would produce contradictory
    messages (one BREAKING, one RISK) for the same event.

    This is a real ABI fact — the library is leaking dependency symbols into its
    public ABI surface — but the verdict is ``COMPATIBLE_WITH_RISK`` rather than
    ``BREAKING``, because direct consumers of this library typically resolve those
    symbols through the dependency directly and are not affected by the leak.

    The risk is that on other systems with a different version of the dependency
    the leaked symbols may differ, causing failures.

    Consider applying ``-fvisibility=hidden`` to prevent this.
    """
    changes: list[Change] = []
    old_syms = old_elf.symbol_map
    new_syms = new_elf.symbol_map

    # Symbols that were *removed* (present in old, absent in new)
    for sym_name, s_old in old_syms.items():
        if sym_name in new_syms:
            # Symbol still exists — skip to avoid double-annotation with
            # _diff_elf_symbol_metadata which handles changed symbols.
            continue
        origin = s_old.origin_lib
        if origin is None:
            continue
        changes.append(Change(
            kind=ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED,
            symbol=sym_name,
            description=(
                f"Symbol '{sym_name}' was removed but appears to originate from "
                f"'{origin}' (a dependency of this library). This is a real ABI "
                f"change — the library is leaking dependency symbols into its public "
                f"ABI surface. Consider applying -fvisibility=hidden."
            ),
            old_value=origin,
            new_value=None,
        ))

    # Symbols that were *added* (absent in old, present in new with origin_lib)
    for sym_name, s_new in new_syms.items():
        if sym_name in old_syms:
            continue  # Already present in old — not a pure addition
        if s_new.origin_lib is None:
            continue
        changes.append(Change(
            kind=ChangeKind.SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED,
            symbol=sym_name,
            description=(
                f"Symbol '{sym_name}' was added but appears to originate from "
                f"'{s_new.origin_lib}' (a dependency of this library). This is a real "
                f"ABI change — the library is leaking dependency symbols into its public "
                f"ABI surface. Consider applying -fvisibility=hidden."
            ),
            old_value=None,
            new_value=s_new.origin_lib,
        ))

    return changes


def _diff_elf_dynamic_section(old_elf: Any, new_elf: Any) -> list[Change]:
    changes: list[Change] = []
    # Emit SONAME_CHANGED only when old library HAD a SONAME (non-empty) and it
    # changed or was removed. Adding a SONAME (empty/None → value) is a compatible
    # improvement and must not be flagged as breaking.
    if old_elf.soname and old_elf.soname != new_elf.soname:
        changes.append(Change(
            kind=ChangeKind.SONAME_CHANGED,
            symbol="DT_SONAME",
            description=f"SONAME changed: {old_elf.soname!r} → {new_elf.soname!r}",
            old_value=old_elf.soname,
            new_value=new_elf.soname,
        ))
    elif not old_elf.soname and new_elf.soname:
        changes.append(Change(
            kind=ChangeKind.SONAME_MISSING,
            symbol="DT_SONAME",
            description=(
                f"Old library has no SONAME (bad practice — packaging/ldconfig will fail); "
                f"new library correctly defines SONAME {new_elf.soname!r}"
            ),
            old_value="",
            new_value=new_elf.soname,
        ))
    changes.extend(_diff_needed_libraries(old_elf.needed, new_elf.needed))
    if old_elf.rpath != new_elf.rpath:
        changes.append(Change(
            kind=ChangeKind.RPATH_CHANGED,
            symbol="DT_RPATH",
            description=f"RPATH changed: {old_elf.rpath!r} → {new_elf.rpath!r}",
            old_value=old_elf.rpath,
            new_value=new_elf.rpath,
        ))
    if old_elf.runpath != new_elf.runpath:
        changes.append(Change(
            kind=ChangeKind.RUNPATH_CHANGED,
            symbol="DT_RUNPATH",
            description=f"RUNPATH changed: {old_elf.runpath!r} → {new_elf.runpath!r}",
            old_value=old_elf.runpath,
            new_value=new_elf.runpath,
        ))
    return changes


def _diff_needed_libraries(old_needed: list[str], new_needed: list[str]) -> list[Change]:
    changes: list[Change] = []
    old_set = set(old_needed)
    new_set = set(new_needed)
    for lib in sorted(new_set - old_set):
        changes.append(Change(
            kind=ChangeKind.NEEDED_ADDED,
            symbol="DT_NEEDED",
            description=f"New dependency added: {lib}",
            new_value=lib,
        ))
    for lib in sorted(old_set - new_set):
        changes.append(Change(
            kind=ChangeKind.NEEDED_REMOVED,
            symbol="DT_NEEDED",
            description=f"Dependency removed: {lib}",
            old_value=lib,
        ))
    return changes


_UNPARSEABLE_VERSION: tuple[int, ...] = (2**31,)
"""Sentinel returned by :func:`_parse_abi_version_tag` for non-numeric tags
like ``GLIBC_PRIVATE``.  Sorts *above* any real version so that a new
non-numeric requirement is always treated as potentially BREAKING — never
silently COMPAT."""


def _parse_abi_version_tag(ver: str) -> tuple[int, ...]:
    """Parse a versioned symbol tag like ``GLIBC_2.34`` or ``GLIBCXX_3.4.19``
    into a comparable integer tuple.

    Only the numeric suffix after the last ``_`` is used:
    ``GLIBC_2.34`` → ``(2, 34)``, ``GLIBCXX_3.4.19`` → ``(3, 4, 19)``.

    Returns :data:`_UNPARSEABLE_VERSION` for non-numeric tags such as
    ``GLIBC_PRIVATE`` — a very large sentinel that always compares as newer
    than any real version, so such tags are conservatively treated as BREAKING.
    """
    parts = ver.rsplit("_", 1)
    numeric = parts[-1] if len(parts) > 1 else ver
    result = tuple(int(x) for x in numeric.split(".") if x.isdigit())
    return result if result else _UNPARSEABLE_VERSION


def _diff_elf_symbol_versioning(old_elf: Any, new_elf: Any) -> list[Change]:
    changes: list[Change] = []
    old_def = set(old_elf.versions_defined)
    new_def = set(new_elf.versions_defined)
    for ver in sorted(old_def - new_def):
        changes.append(Change(
            kind=ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED,
            symbol=ver,
            description=f"Symbol version removed: {ver}",
            old_value=ver,
        ))
    for ver in sorted(new_def - old_def):
        changes.append(Change(
            kind=ChangeKind.SYMBOL_VERSION_DEFINED_ADDED,
            symbol=ver,
            description=f"Symbol version definition added: {ver}",
            new_value=ver,
        ))

    all_req_libs = set(old_elf.versions_required) | set(new_elf.versions_required)
    for lib in sorted(all_req_libs):
        old_vers = set(old_elf.versions_required.get(lib, []))
        new_vers = set(new_elf.versions_required.get(lib, []))
        # The old maximum requirement for this lib — anything added that
        # is *older* than this maximum is not a new constraint on the caller.
        # If the lib is entirely new (not in old at all), its version
        # requirements are already captured by needed_added → COMPATIBLE.
        lib_is_new = lib not in old_elf.versions_required and lib not in getattr(old_elf, "needed", [])

        # Compute old max PER VERSION-TAG PREFIX (e.g. "GLIBC", "GLIBCXX", "CXXABI")
        # to avoid cross-namespace bleed: GLIBCXX_3.4.32 must not suppress a
        # genuinely newer CXXABI_1.3.14 requirement.
        def _old_max_for_prefix(prefix: str, _old_vers: set[str] = old_vers) -> tuple[int, ...]:  # pylint: disable=dangerous-default-value
            matching = [_parse_abi_version_tag(v) for v in _old_vers
                        if v.startswith(prefix + "_")]
            return max(matching, default=(0,))

        for ver in sorted(new_vers - old_vers):
            ver_tuple = _parse_abi_version_tag(ver)
            prefix = ver.rsplit("_", 1)[0] if "_" in ver else ver
            old_max = _old_max_for_prefix(prefix)
            if lib_is_new or ver_tuple <= old_max:
                # Either the whole lib is new (covered by needed_added), or the
                # added requirement is not newer than the old max — COMPATIBLE.
                changes.append(Change(
                    kind=ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED_COMPAT,
                    symbol=ver,
                    description=(
                        f"New symbol version requirement: {ver} (from {lib})"
                        f" — not newer than previous max, backward-compatible"
                    ),
                    new_value=f"{lib}:{ver}",
                ))
            else:
                # Genuinely newer requirement — callers on older runtimes will fail.
                changes.append(Change(
                    kind=ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED,
                    symbol=ver,
                    description=f"New symbol version requirement: {ver} (from {lib})",
                    new_value=f"{lib}:{ver}",
                ))
        for ver in sorted(old_vers - new_vers):
            changes.append(Change(
                kind=ChangeKind.SYMBOL_VERSION_REQUIRED_REMOVED,
                symbol=ver,
                description=f"Symbol version requirement removed: {ver} (from {lib})",
                old_value=f"{lib}:{ver}",
            ))
    return changes


def _diff_elf_symbol_metadata(old_elf: Any, new_elf: Any) -> list[Change]:
    changes: list[Change] = []
    old_syms = old_elf.symbol_map
    new_syms = new_elf.symbol_map

    for sym_name, s_old in old_syms.items():
        s_new = new_syms.get(sym_name)
        if s_new is None:
            continue
        changes.extend(_diff_elf_symbol_pair(sym_name, s_old, s_new))

    for sym_name, s_new in new_syms.items():
        if s_new.sym_type != SymbolType.COMMON:
            continue
        old_common = old_syms.get(sym_name)
        if old_common is None or old_common.sym_type != SymbolType.COMMON:
            changes.append(Change(
                kind=ChangeKind.COMMON_SYMBOL_RISK,
                symbol=sym_name,
                description=f"Exported STT_COMMON symbol: {sym_name} (resolution depends on linker/loader)",
            ))
    return changes


def _diff_elf_symbol_pair(sym_name: str, s_old: Any, s_new: Any) -> list[Change]:
    changes: list[Change] = []
    if s_old.sym_type != SymbolType.IFUNC and s_new.sym_type == SymbolType.IFUNC:
        changes.append(Change(
            kind=ChangeKind.IFUNC_INTRODUCED,
            symbol=sym_name,
            description=f"Symbol became GNU_IFUNC: {sym_name}",
            old_value=s_old.sym_type.value,
            new_value="ifunc",
        ))
    elif s_old.sym_type == SymbolType.IFUNC and s_new.sym_type != SymbolType.IFUNC:
        changes.append(Change(
            kind=ChangeKind.IFUNC_REMOVED,
            symbol=sym_name,
            description=f"Symbol no longer GNU_IFUNC: {sym_name}",
            old_value="ifunc",
            new_value=s_new.sym_type.value,
        ))
    elif s_old.sym_type != s_new.sym_type:
        changes.append(Change(
            kind=ChangeKind.SYMBOL_TYPE_CHANGED,
            symbol=sym_name,
            description=f"Symbol type changed: {sym_name} ({s_old.sym_type.value} → {s_new.sym_type.value})",
            old_value=s_old.sym_type.value,
            new_value=s_new.sym_type.value,
        ))

    if s_old.binding != s_new.binding:
        is_weakening = s_old.binding == SymbolBinding.GLOBAL and s_new.binding == SymbolBinding.WEAK
        kind = ChangeKind.SYMBOL_BINDING_CHANGED if is_weakening else ChangeKind.SYMBOL_BINDING_STRENGTHENED
        changes.append(Change(
            kind=kind,
            symbol=sym_name,
            description=f"Symbol binding changed: {sym_name} ({s_old.binding.value} → {s_new.binding.value})",
            old_value=s_old.binding.value,
            new_value=s_new.binding.value,
        ))

    if (
        s_old.size > 0
        and s_new.size > 0
        and s_old.size != s_new.size
        and s_new.sym_type in (SymbolType.OBJECT, SymbolType.COMMON, SymbolType.TLS)
    ):
        changes.append(Change(
            kind=ChangeKind.SYMBOL_SIZE_CHANGED,
            symbol=sym_name,
            description=f"Symbol size changed: {sym_name} ({s_old.size} → {s_new.size} bytes)",
            old_value=str(s_old.size),
            new_value=str(s_new.size),
        ))
    return changes


# ── Post-processing: enrich and deduplicate ────────────────────────────────

# Mapping from DWARF change kinds to their AST equivalents for deduplication.
_DWARF_TO_AST_EQUIV: dict[ChangeKind, set[ChangeKind]] = {
    ChangeKind.STRUCT_SIZE_CHANGED: {ChangeKind.TYPE_SIZE_CHANGED},
    ChangeKind.STRUCT_ALIGNMENT_CHANGED: {ChangeKind.TYPE_ALIGNMENT_CHANGED},
    ChangeKind.STRUCT_FIELD_OFFSET_CHANGED: {ChangeKind.TYPE_FIELD_OFFSET_CHANGED},
    ChangeKind.STRUCT_FIELD_REMOVED: {ChangeKind.TYPE_FIELD_REMOVED},
    ChangeKind.STRUCT_FIELD_TYPE_CHANGED: {ChangeKind.TYPE_FIELD_TYPE_CHANGED},
}

# Type/enum/struct change kinds for which affected-symbol enrichment makes sense.
_TYPE_CHANGE_KINDS: frozenset[ChangeKind] = frozenset({
    ChangeKind.TYPE_SIZE_CHANGED, ChangeKind.TYPE_ALIGNMENT_CHANGED,
    ChangeKind.TYPE_FIELD_REMOVED, ChangeKind.TYPE_FIELD_ADDED,
    ChangeKind.TYPE_FIELD_OFFSET_CHANGED, ChangeKind.TYPE_FIELD_TYPE_CHANGED,
    ChangeKind.TYPE_BASE_CHANGED, ChangeKind.TYPE_VTABLE_CHANGED,
    ChangeKind.TYPE_REMOVED, ChangeKind.TYPE_FIELD_ADDED_COMPATIBLE,
    ChangeKind.TYPE_BECAME_OPAQUE,
    ChangeKind.BASE_CLASS_POSITION_CHANGED, ChangeKind.BASE_CLASS_VIRTUAL_CHANGED,
    ChangeKind.ENUM_MEMBER_REMOVED, ChangeKind.ENUM_MEMBER_ADDED,
    ChangeKind.ENUM_MEMBER_VALUE_CHANGED, ChangeKind.ENUM_LAST_MEMBER_VALUE_CHANGED,
    ChangeKind.ENUM_UNDERLYING_SIZE_CHANGED,
    ChangeKind.UNION_FIELD_ADDED, ChangeKind.UNION_FIELD_REMOVED,
    ChangeKind.UNION_FIELD_TYPE_CHANGED, ChangeKind.TYPEDEF_BASE_CHANGED,
    ChangeKind.STRUCT_SIZE_CHANGED, ChangeKind.STRUCT_FIELD_OFFSET_CHANGED,
    ChangeKind.STRUCT_FIELD_REMOVED, ChangeKind.STRUCT_FIELD_TYPE_CHANGED,
    ChangeKind.STRUCT_ALIGNMENT_CHANGED,
})


def _enrich_source_locations(
    changes: list[Change], old: AbiSnapshot, new: AbiSnapshot,
) -> None:
    """Fill in source_location on Changes from the model data."""
    # Build type→location lookup
    type_loc: dict[str, str] = {}
    for t in old.types:
        if t.source_location:
            type_loc[t.name] = t.source_location
    for t in new.types:
        if t.source_location:
            type_loc.setdefault(t.name, t.source_location)

    # Build function→location lookup
    func_loc: dict[str, str] = {}
    for f in old.functions:
        if f.source_location:
            func_loc[f.mangled] = f.source_location
    for f in new.functions:
        if f.source_location:
            func_loc.setdefault(f.mangled, f.source_location)

    # Build variable→location lookup
    var_loc: dict[str, str] = {}
    for v in old.variables:
        if v.source_location:
            var_loc[v.mangled] = v.source_location
    for v in new.variables:
        if v.source_location:
            var_loc.setdefault(v.mangled, v.source_location)

    for c in changes:
        if c.source_location:
            continue
        # Try function/variable first (symbol is mangled name), then type name
        loc = func_loc.get(c.symbol) or var_loc.get(c.symbol) or type_loc.get(c.symbol)
        # For qualified symbols like "MyStruct::field", fall back to base type name
        if not loc and "::" in c.symbol:
            base_type = c.symbol.split("::")[0]
            loc = type_loc.get(base_type)
        if loc:
            c.source_location = loc


def _enrich_affected_symbols(
    changes: list[Change], old: AbiSnapshot,
) -> None:
    """For type/enum changes, find exported functions that use the affected type."""
    # Only compute if there are type-related changes
    type_changes = [c for c in changes if c.kind in _TYPE_CHANGE_KINDS]
    if not type_changes:
        return

    # Collect affected type names
    affected_types: set[str] = set()
    for c in type_changes:
        # symbol is the type name (e.g. "Point", "Container", "Status")
        # Strip field qualifiers like "Container::flags" → "Container"
        type_name = c.symbol.split("::")[0] if "::" in c.symbol else c.symbol
        affected_types.add(type_name)

    if not affected_types:
        return

    # Build type→functions mapping from old snapshot
    type_to_funcs: dict[str, list[str]] = {t: [] for t in affected_types}
    old_pub = _public_functions(old)
    for _mangled, func in old_pub.items():
        # Check return type
        func_types_used: set[str] = set()
        if func.return_type:
            func_types_used.add(func.return_type)
        for p in func.params:
            if p.type:
                func_types_used.add(p.type)

        for tname in affected_types:
            # Check if the type name appears in any parameter or return type
            if any(tname in ft for ft in func_types_used):
                type_to_funcs[tname].append(func.name)

    # Also check if types are embedded in struct fields used by functions
    # (e.g., Container has a Leaf field → functions taking Container* are affected by Leaf changes)
    type_embeds: dict[str, set[str]] = {}  # child_type → {parent_type, ...}
    for t in old.types:
        for fld in t.fields:
            for tname in affected_types:
                if tname in fld.type:
                    type_embeds.setdefault(tname, set()).add(t.name)

    # Compute transitive closure: if Leaf is in Container is in Wrapper,
    # functions using Wrapper are also affected by Leaf changes.
    def _all_ancestors(tname: str) -> set[str]:
        """BFS over type_embeds to find all transitive parent types."""
        visited: set[str] = set()
        queue = list(type_embeds.get(tname, set()))
        while queue:
            parent = queue.pop()
            if parent in visited:
                continue
            visited.add(parent)
            queue.extend(type_embeds.get(parent, set()))
        return visited

    for tname in affected_types:
        ancestors = _all_ancestors(tname)
        for parent in ancestors:
            if parent in type_to_funcs:
                type_to_funcs[tname].extend(type_to_funcs[parent])
            else:
                # Check functions for parent too
                for _mangled, func in old_pub.items():
                    func_types_used = {func.return_type} | {p.type for p in func.params}
                    if any(parent in ft for ft in func_types_used if ft):
                        type_to_funcs[tname].append(func.name)

    # Assign to changes
    for c in type_changes:
        type_name = c.symbol.split("::")[0] if "::" in c.symbol else c.symbol
        funcs = type_to_funcs.get(type_name, [])
        if funcs:
            # Deduplicate and sort
            c.affected_symbols = sorted(set(funcs))


def _deduplicate_ast_dwarf(changes: list[Change]) -> list[Change]:
    """Remove DWARF findings that duplicate an AST finding for the same symbol.

    Two dedup passes:

    1. **Exact dedup** — collapses entries with the same ``(kind, description)``.
       Using description (not symbol) handles cases where the same logical
       finding is reported under different symbol granularities (e.g. ``Status``
       vs ``Status::FOO``).

    2. **Cross-kind dedup** — drops a DWARF finding when an equivalent AST
       finding exists for the *same full symbol* (e.g. STRUCT_SIZE_CHANGED for
       ``S`` is dropped when TYPE_SIZE_CHANGED for ``S`` is already present).
       Full-symbol matching prevents collapsing different fields of the same
       type (``S::a`` vs ``S::b``).
    """
    # First pass: index all findings by (kind, symbol) for cross-kind dedup
    ast_findings: set[tuple[str, str]] = set()
    for c in changes:
        ast_findings.add((c.kind.value, c.symbol))

    # Second pass: filter out DWARF duplicates
    result: list[Change] = []
    seen: set[tuple[str, str]] = set()  # exact dedup by (kind, description)
    for c in changes:
        key = (c.kind.value, c.description)
        # Exact dedup: same kind + same description = same finding
        if key in seen:
            continue
        seen.add(key)

        # Check if this DWARF finding has an AST equivalent already present
        equiv_ast_kinds = _DWARF_TO_AST_EQUIV.get(c.kind)
        if equiv_ast_kinds:
            if any((ak.value, c.symbol) in ast_findings for ak in equiv_ast_kinds):
                continue  # skip DWARF duplicate
        result.append(c)
    return result


def compare(
    old: AbiSnapshot,
    new: AbiSnapshot,
    suppression: SuppressionList | None = None,
    *,
    policy: str = "strict_abi",
    policy_file: PolicyFile | None = None,
) -> DiffResult:
    """Diff two AbiSnapshots and return a DiffResult with verdict.

    Args:
        old: Old ABI snapshot.
        new: New ABI snapshot.
        suppression: Optional suppression list to filter known changes.
        policy: Policy profile name to use for verdict classification.
            Available: "strict_abi" (default), "sdk_vendor", "plugin_abi".
            Ignored when *policy_file* is provided.
        policy_file: Optional :class:`~abicheck.policy_file.PolicyFile` instance
            for user-defined per-kind verdict overrides.  When provided,
            *policy* is used only as the ``base_policy`` fallback inside the
            file (i.e. the file's own ``base_policy`` field takes precedence).
    """

    detector_fns: list[_DetectorSpec] = [
        _DetectorSpec("functions", _diff_functions),
        _DetectorSpec("variables", _diff_variables),
        _DetectorSpec("types", _diff_types),
        _DetectorSpec("enums", _diff_enums),
        _DetectorSpec("method_qualifiers", _diff_method_qualifiers),
        _DetectorSpec("unions", _diff_unions),
        _DetectorSpec("typedefs", _diff_typedefs),
        _DetectorSpec("elf", _diff_elf),
        _DetectorSpec(
            "pe",
            _diff_pe,
            lambda o, n: (
                o.pe is not None and n.pe is not None,
                "missing PE metadata",
            ),
        ),
        _DetectorSpec(
            "macho",
            _diff_macho,
            lambda o, n: (
                o.macho is not None and n.macho is not None,
                "missing Mach-O metadata",
            ),
        ),
        _DetectorSpec("dwarf", _diff_dwarf),
        _DetectorSpec(
            "advanced_dwarf",
            _diff_advanced_dwarf,
            lambda o, n: ((o.dwarf_advanced is not None and n.dwarf_advanced is not None), "missing DWARF advanced metadata"),
        ),
        _DetectorSpec("enum_renames", _diff_enum_renames),
        _DetectorSpec("field_qualifiers", _diff_field_qualifiers),
        _DetectorSpec("field_renames", _diff_field_renames),
        _DetectorSpec("param_defaults", _diff_param_defaults),
        _DetectorSpec("param_renames", _diff_param_renames),
        _DetectorSpec("pointer_levels", _diff_pointer_levels),
        _DetectorSpec("access_levels", _diff_access_levels),
        _DetectorSpec("anon_fields", _diff_anon_fields),
        _DetectorSpec("var_values", _diff_var_values),
        _DetectorSpec("type_kind_changes", _diff_type_kind_changes),
        _DetectorSpec("reserved_fields", _diff_reserved_fields),
        _DetectorSpec("const_overloads", _diff_const_overloads),
        _DetectorSpec("param_restrict", _diff_param_restrict),
        _DetectorSpec("param_va_list", _diff_param_va_list),
        _DetectorSpec("constants", _diff_constants),
        _DetectorSpec("var_access", _diff_var_access),
        _DetectorSpec("elf_deleted_fallback", _diff_elf_deleted_fallback),
        _DetectorSpec("template_inner_types", _diff_template_inner_types),
    ]

    changes: list[Change] = []
    detector_results: list[DetectorResult] = []
    for spec in detector_fns:
        enabled, reason = spec.support(old, new)
        if not enabled:
            detector_results.append(
                DetectorResult(name=spec.name, changes_count=0, enabled=False, coverage_gap=reason)
            )
            continue

        detected = spec.run(old, new)
        changes.extend(detected)
        detector_results.append(DetectorResult(name=spec.name, changes_count=len(detected), enabled=True))

    # Deduplicate AST/DWARF before suppression so a single canonical change
    # remains for suppression matching (avoids suppressed AST entry leaving
    # an unsuppressed DWARF duplicate).
    changes = _deduplicate_ast_dwarf(changes)

    # Enrich source locations before suppression so source_location-based
    # suppression rules can match (most changes have source_location=None
    # until enrichment runs).
    _enrich_source_locations(changes, old, new)

    suppressed: list[Change] = []
    if suppression is not None:
        filtered: list[Change] = []
        for c in changes:
            if suppression.is_suppressed(c):
                suppressed.append(c)
            else:
                filtered.append(c)
        changes = filtered

    # Post-processing: enrich remaining changes with affected symbols
    _enrich_affected_symbols(changes, old)

    verdict = policy_file.compute_verdict(changes) if policy_file is not None else compute_verdict(changes, policy=policy)
    effective_policy = policy_file.base_policy if policy_file is not None else policy
    return DiffResult(
        old_version=old.version,
        new_version=new.version,
        library=old.library,
        changes=changes,
        verdict=verdict,
        suppressed_count=len(suppressed),
        suppressed_changes=suppressed,
        suppression_file_provided=suppression is not None,
        detector_results=detector_results,
        policy=effective_policy,
    )


# ── ABICC full parity detectors ───────────────────────────────────────────────


def _diff_var_values(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect global data value changes (ABICC: Global_Data_Value_Changed).

    When a global const variable's initial value changes, old binaries may
    use stale compile-time-inlined values (constant propagation).
    """
    changes: list[Change] = []
    old_map = _public_variables(old)
    new_map = _public_variables(new)

    for mangled, v_old in old_map.items():
        v_new = new_map.get(mangled)
        if v_new is None:
            continue
        if (
            v_old.value is not None
            and v_new.value is not None
            and v_old.value != v_new.value
        ):
            changes.append(Change(
                kind=ChangeKind.VAR_VALUE_CHANGED,
                symbol=mangled,
                description=f"Global data value changed: {v_old.name} ({v_old.value!r} → {v_new.value!r})",
                old_value=v_old.value,
                new_value=v_new.value,
            ))
    return changes


def _diff_type_kind_changes(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect struct↔union kind changes (ABICC: StructToUnion / DataType_Type)."""
    changes: list[Change] = []
    old_map = {t.name: t for t in old.types}
    new_map = {t.name: t for t in new.types}

    for name, t_old in old_map.items():
        t_new = new_map.get(name)
        if t_new is None:
            continue
        if t_old.kind != t_new.kind:
            # Union-involving transitions are binary-breaking (layout changes);
            # struct↔class transitions are source-level only (identical ABI).
            union_involved = t_old.kind == "union" or t_new.kind == "union"
            ck = ChangeKind.TYPE_KIND_CHANGED if union_involved else ChangeKind.SOURCE_LEVEL_KIND_CHANGED
            changes.append(Change(
                kind=ck,
                symbol=name,
                description=f"Aggregate kind changed: {name} ({t_old.kind} → {t_new.kind})",
                old_value=t_old.kind,
                new_value=t_new.kind,
            ))
    return changes


def _diff_reserved_fields(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect reserved fields put into use (ABICC: Used_Reserved_Field).

    Heuristic: a field whose name matches common reserved patterns
    (e.g. __reserved, _reserved, reserved, __pad, _pad) in old version
    is renamed to a non-reserved name in new version at the same offset.
    """
    import re

    _RESERVED_RE = re.compile(r"^_{0,2}(reserved|pad|padding|spare|unused)\d*$", re.IGNORECASE)  # pylint: disable=invalid-name
    changes: list[Change] = []
    old_map = {t.name: t for t in old.types if not t.is_union}
    new_map = {t.name: t for t in new.types if not t.is_union}

    for name, t_old in old_map.items():
        t_new = new_map.get(name)
        if t_new is None or t_new.is_opaque:
            continue

        old_names = {f.name for f in t_old.fields}
        new_names = {f.name for f in t_new.fields}

        removed = [f for f in t_old.fields if f.name not in new_names and _RESERVED_RE.match(f.name)]
        added = [f for f in t_new.fields if f.name not in old_names and not _RESERVED_RE.match(f.name)]

        added_by_offset = {f.offset_bits: f for f in added if f.offset_bits is not None}
        for f_old in removed:
            if f_old.offset_bits is None:
                continue
            f_new = added_by_offset.get(f_old.offset_bits)
            if f_new is not None:
                changes.append(Change(
                    kind=ChangeKind.USED_RESERVED_FIELD,
                    symbol=name,
                    description=f"Reserved field put into use: {name}::{f_old.name} → {f_new.name}",
                    old_value=f_old.name,
                    new_value=f_new.name,
                ))
    return changes


def _diff_const_overloads(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect removed const method overloads (ABICC: Removed_Const_Overload).

    A const overload removal occurs when both const and non-const versions
    existed in old, but only the non-const version remains in new.
    """
    changes: list[Change] = []
    old_funcs = [f for f in old.functions if f.visibility in _PUBLIC_VIS]
    new_funcs = [f for f in new.functions if f.visibility in _PUBLIC_VIS]

    # Group by (name, param_signature) to find const/non-const pairs
    from collections import defaultdict

    _ParamSig = tuple[str, int, str]  # (type, pointer_depth, kind)
    _GroupKey = tuple[str, tuple[_ParamSig, ...]]

    def _group_key(f: Function) -> _GroupKey:
        return (f.name, tuple((p.type, p.pointer_depth, p.kind.value) for p in f.params))

    old_groups: dict[_GroupKey, list[Function]] = defaultdict(list)
    new_groups: dict[_GroupKey, list[Function]] = defaultdict(list)
    for f in old_funcs:
        old_groups[_group_key(f)].append(f)
    for f in new_funcs:
        new_groups[_group_key(f)].append(f)

    for key, old_fns in old_groups.items():
        old_const = [f for f in old_fns if f.is_const]
        old_nonconst = [f for f in old_fns if not f.is_const]
        if not old_const or not old_nonconst:
            continue  # no const overload pair in old

        new_fns = new_groups.get(key, [])
        new_const = [f for f in new_fns if f.is_const]
        new_nonconst = [f for f in new_fns if not f.is_const]
        if not new_const and new_nonconst:
            # Const overload removed, non-const kept
            f_removed = old_const[0]
            changes.append(Change(
                kind=ChangeKind.REMOVED_CONST_OVERLOAD,
                symbol=f_removed.mangled,
                description=f"Const method overload removed: {f_removed.name} (non-const version still exists)",
                old_value="const overload present",
                new_value="const overload removed",
            ))
    return changes


def _diff_param_restrict(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect restrict qualifier changes on parameters (ABICC: Parameter_Became_Restrict)."""
    changes: list[Change] = []
    old_map = _public_functions(old)
    new_map = _public_functions(new)

    for mangled, f_old in old_map.items():
        f_new = new_map.get(mangled)
        if f_new is None:
            continue
        for i, (p_old, p_new) in enumerate(zip(f_old.params, f_new.params)):
            if p_old.is_restrict != p_new.is_restrict:
                direction = "added" if p_new.is_restrict else "removed"
                changes.append(Change(
                    kind=ChangeKind.PARAM_RESTRICT_CHANGED,
                    symbol=mangled,
                    description=f"Parameter restrict qualifier {direction}: {f_old.name} param {p_old.name or i}",
                    old_value=f"restrict={p_old.is_restrict}",
                    new_value=f"restrict={p_new.is_restrict}",
                ))
    return changes


def _diff_param_va_list(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect va_list parameter changes (ABICC: Parameter_Became_VaList/Non_VaList)."""
    changes: list[Change] = []
    old_map = _public_functions(old)
    new_map = _public_functions(new)

    for mangled, f_old in old_map.items():
        f_new = new_map.get(mangled)
        if f_new is None:
            continue
        for i, (p_old, p_new) in enumerate(zip(f_old.params, f_new.params)):
            if not p_old.is_va_list and p_new.is_va_list:
                changes.append(Change(
                    kind=ChangeKind.PARAM_BECAME_VA_LIST,
                    symbol=mangled,
                    description=f"Parameter became va_list: {f_old.name} param {p_old.name or i}",
                    old_value=p_old.type,
                    new_value="va_list",
                ))
            elif p_old.is_va_list and not p_new.is_va_list:
                changes.append(Change(
                    kind=ChangeKind.PARAM_LOST_VA_LIST,
                    symbol=mangled,
                    description=f"Parameter was va_list, now fixed: {f_old.name} param {p_old.name or i}",
                    old_value="va_list",
                    new_value=p_new.type,
                ))
    return changes


def _diff_constants(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect preprocessor constant (#define) changes (ABICC: Changed/Added/Removed_Constant)."""
    changes: list[Change] = []
    old_consts = old.constants
    new_consts = new.constants

    for name, old_val in old_consts.items():
        new_val = new_consts.get(name)
        if new_val is None:
            changes.append(Change(
                kind=ChangeKind.CONSTANT_REMOVED,
                symbol=name,
                description=f"Preprocessor constant removed: {name}",
                old_value=old_val,
            ))
        elif new_val != old_val:
            changes.append(Change(
                kind=ChangeKind.CONSTANT_CHANGED,
                symbol=name,
                description=f"Preprocessor constant value changed: {name} ({old_val!r} → {new_val!r})",
                old_value=old_val,
                new_value=new_val,
            ))

    for name, new_val in new_consts.items():
        if name not in old_consts:
            changes.append(Change(
                kind=ChangeKind.CONSTANT_ADDED,
                symbol=name,
                description=f"New preprocessor constant: {name}",
                new_value=new_val,
            ))
    return changes


def _diff_var_access(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect global data access level changes (ABICC: Global_Data_Became_Private/Protected/Public)."""
    changes: list[Change] = []
    old_map = _public_variables(old)
    new_map = _public_variables(new)

    for mangled, v_old in old_map.items():
        v_new = new_map.get(mangled)
        if v_new is None:
            continue
        if v_old.access != v_new.access:
            if _is_access_narrowing(v_old.access, v_new.access):
                changes.append(Change(
                    kind=ChangeKind.VAR_ACCESS_CHANGED,
                    symbol=mangled,
                    description=f"Variable access level narrowed: {v_old.name} ({v_old.access.value} → {v_new.access.value})",
                    old_value=v_old.access.value,
                    new_value=v_new.access.value,
                ))
            else:
                changes.append(Change(
                    kind=ChangeKind.VAR_ACCESS_WIDENED,
                    symbol=mangled,
                    description=f"Variable access level widened: {v_old.name} ({v_old.access.value} → {v_new.access.value})",
                    old_value=v_old.access.value,
                    new_value=v_new.access.value,
                ))
    return changes


# ── Sprint 3: DWARF-aware layout diff ────────────────────────────────────────

def _diff_dwarf(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """DWARF-aware struct/enum layout detectors (Sprint 3).

    Requires binaries compiled with -g.

    Graceful degradation rules:
    - Neither side has DWARF → skip silently (no false positives)
    - Old has DWARF, new is stripped → emit DWARF_INFO_MISSING warning change
      so callers know the comparison is incomplete (not silently COMPATIBLE)
    - Only new has DWARF → can't compare without old baseline → skip

    Important: we diff only ABI-reachable types/enums discovered from the
    header model (castxml layer). This avoids flagging private implementation
    types present in DWARF but not in the public API surface.
    """
    import logging as _logging

    from .dwarf_metadata import DwarfMetadata

    _log = _logging.getLogger(__name__)

    o: DwarfMetadata = getattr(old, "dwarf", None) or DwarfMetadata()
    n: DwarfMetadata = getattr(new, "dwarf", None) or DwarfMetadata()

    if not o.has_dwarf and not n.has_dwarf:
        return []  # neither side has DWARF — nothing to compare

    if o.has_dwarf and not n.has_dwarf:
        _log.warning(
            "DWARF layout comparison skipped: new binary has no debug info. "
            "Recompile with -g to enable struct/enum ABI checks."
        )
        return [Change(
            kind=ChangeKind.DWARF_INFO_MISSING,
            symbol="<dwarf>",
            description=(
                "New binary has no DWARF debug info — struct/enum layout "
                "comparison was skipped. Recompile with -g to enable."
            ),
        )]

    def _allow_name(name: str, allowed: set[str]) -> bool:
        # Match by full name or by unqualified name (last component after ::)
        return name in allowed or name.split("::")[-1] in allowed

    allowed_structs: set[str] = {
        t.name for t in old.types
    } | {
        t.name for t in new.types
    }
    allowed_enums: set[str] = {
        e.name for e in old.enums
    } | {
        e.name for e in new.enums
    }

    # If the header model is absent (no castxml data), fall back to comparing
    # all DWARF types — this preserves compatibility when running DWARF-only.
    if allowed_structs:
        o_structs = {k: v for k, v in o.structs.items() if _allow_name(k, allowed_structs)}
        n_structs = {k: v for k, v in n.structs.items() if _allow_name(k, allowed_structs)}
    else:
        o_structs = o.structs
        n_structs = n.structs

    if allowed_enums:
        o_enums = {k: v for k, v in o.enums.items() if _allow_name(k, allowed_enums)}
        n_enums = {k: v for k, v in n.enums.items() if _allow_name(k, allowed_enums)}
    else:
        o_enums = o.enums
        n_enums = n.enums

    filtered_old = DwarfMetadata(structs=o_structs, enums=o_enums, has_dwarf=o.has_dwarf)
    filtered_new = DwarfMetadata(structs=n_structs, enums=n_enums, has_dwarf=n.has_dwarf)

    changes: list[Change] = []
    changes.extend(_diff_struct_layouts(filtered_old, filtered_new))
    changes.extend(_diff_enum_layouts(filtered_old, filtered_new))
    return changes


def _normalize_type_name(name: str) -> str:
    """Normalize a C/C++ type name for stable DWARF↔castxml comparison.

    Strips leading/trailing whitespace, CV-qualifiers, pointer/reference
    decorations, and 'struct'/'class'/'union' tag keywords so that semantically
    equivalent names compare equal regardless of DWARF vs castxml source:

    Examples::

        "struct Foo"     → "Foo"
        "const struct Foo *" → "Foo"
        "class Bar &"    → "Bar"
        "union U"        → "U"
        "int"            → "int"   (unchanged)

    Note: this normalizer is intentionally lossy for comparison purposes only.
    The original type names are still preserved in Change.old_value/new_value.
    """
    import re as _re
    s = name.strip()
    # Remove trailing pointer/reference decorators and CV-qualifiers
    s = _re.sub(r"[\s*&]+$", "", s).strip()
    # Remove leading CV-qualifiers
    s = _re.sub(r"^(const|volatile)(\s+(const|volatile))?\s+", "", s).strip()
    # Remove struct/class/union tag keyword
    s = _re.sub(r"^(struct|class|union)\s+", "", s).strip()
    return s


def _diff_struct_layouts(o: object, n: object) -> list[Change]:
    from .dwarf_metadata import StructLayout

    old_structs: dict[str, StructLayout] = getattr(o, "structs", {})
    new_structs: dict[str, StructLayout] = getattr(n, "structs", {})
    changes: list[Change] = []

    for name, old_s in old_structs.items():
        if name not in new_structs:
            continue  # struct removed — caught by header-layer (castxml)

        new_s = new_structs[name]

        # 1. Total size
        if old_s.byte_size != new_s.byte_size:
            changes.append(Change(
                kind=ChangeKind.STRUCT_SIZE_CHANGED,
                symbol=name,
                description=(
                    f"Struct size changed: {name} "
                    f"({old_s.byte_size} → {new_s.byte_size} bytes)"
                ),
                old_value=str(old_s.byte_size),
                new_value=str(new_s.byte_size),
            ))

        # 2. Alignment (only when explicitly present in DWARF 5)
        if old_s.alignment and new_s.alignment and old_s.alignment != new_s.alignment:
            changes.append(Change(
                kind=ChangeKind.STRUCT_ALIGNMENT_CHANGED,
                symbol=name,
                description=(
                    f"Struct alignment changed: {name} "
                    f"({old_s.alignment} → {new_s.alignment})"
                ),
                old_value=str(old_s.alignment),
                new_value=str(new_s.alignment),
            ))

        # Build field maps
        old_fields = {f.name: f for f in old_s.fields}
        new_fields = {f.name: f for f in new_s.fields}

        # 3. Removed fields
        for fname in sorted(old_fields.keys() - new_fields.keys()):
            changes.append(Change(
                kind=ChangeKind.STRUCT_FIELD_REMOVED,
                symbol=f"{name}::{fname}",
                description=f"Struct field removed: {name}::{fname}",
                old_value=f"{old_fields[fname].type_name}",
            ))

        # 4. Existing fields: offset and type changes
        for fname, old_f in old_fields.items():
            if fname not in new_fields:
                continue
            new_f = new_fields[fname]

            if old_f.byte_offset != new_f.byte_offset:
                changes.append(Change(
                    kind=ChangeKind.STRUCT_FIELD_OFFSET_CHANGED,
                    symbol=f"{name}::{fname}",
                    description=(
                        f"Field offset changed: {name}::{fname} "
                        f"(+{old_f.byte_offset} → +{new_f.byte_offset})"
                    ),
                    old_value=str(old_f.byte_offset),
                    new_value=str(new_f.byte_offset),
                ))

            # Field type drift:
            # - catches same-size type substitutions (int→float, Foo*→Bar*)
            # - strip "struct "/"class "/"union " prefixes for stable comparison
            # - still includes explicit size drift when known on both sides
            type_name_changed = _normalize_type_name(old_f.type_name) != _normalize_type_name(new_f.type_name)
            type_size_changed = (
                old_f.byte_size > 0
                and new_f.byte_size > 0
                and old_f.byte_size != new_f.byte_size
            )
            if type_name_changed or type_size_changed:
                changes.append(Change(
                    kind=ChangeKind.STRUCT_FIELD_TYPE_CHANGED,
                    symbol=f"{name}::{fname}",
                    description=(
                        f"Field type changed: {name}::{fname} "
                        f"{old_f.type_name}({old_f.byte_size}B) → "
                        f"{new_f.type_name}({new_f.byte_size}B)"
                    ),
                    old_value=old_f.type_name,
                    new_value=new_f.type_name,
                ))

    return changes


def _diff_enum_layouts(o: object, n: object) -> list[Change]:
    from .dwarf_metadata import EnumInfo

    old_enums: dict[str, EnumInfo] = getattr(o, "enums", {})
    new_enums: dict[str, EnumInfo] = getattr(n, "enums", {})
    changes: list[Change] = []

    for name, old_e in old_enums.items():
        if name not in new_enums:
            continue

        new_e = new_enums[name]

        # 1. Underlying size change (e.g. int8_t → int32_t)
        if old_e.underlying_byte_size != new_e.underlying_byte_size:
            changes.append(Change(
                kind=ChangeKind.ENUM_UNDERLYING_SIZE_CHANGED,
                symbol=name,
                description=(
                    f"Enum underlying type size changed: {name} "
                    f"({old_e.underlying_byte_size} → {new_e.underlying_byte_size} bytes)"
                ),
                old_value=str(old_e.underlying_byte_size),
                new_value=str(new_e.underlying_byte_size),
            ))

        # 2. Removed members — skip rename-only removals here.
        # A dedicated rename detector emits ENUM_MEMBER_RENAMED. Here we only
        # report truly removed values. Use one-to-one proof: a removal is a
        # rename candidate only when its value appears in exactly one new-only
        # member (CodeRabbit P1: avoid false suppression with alias-heavy enums).
        _removed_names = {m for m in old_e.members if m not in new_e.members}
        _added_names = {m for m in new_e.members if m not in old_e.members}
        # Build set of removed old-member names whose value uniquely maps to one new name
        _renamed_old: set[str] = set()
        _claimed_new: set[str] = set()
        for _rname in sorted(_removed_names):
            _rval = old_e.members[_rname]
            _candidates = [_n for _n in _added_names if new_e.members[_n] == _rval and _n not in _claimed_new]
            if len(_candidates) == 1:
                _renamed_old.add(_rname)
                _claimed_new.add(_candidates[0])
        for mname in sorted(_removed_names):
            if mname in _renamed_old:
                continue
            old_val = old_e.members[mname]
            changes.append(Change(
                kind=ChangeKind.ENUM_MEMBER_REMOVED,
                symbol=f"{name}::{mname}",
                description=f"Enum member removed: {name}::{mname}",
                old_value=str(old_val),
            ))

        # 3. Changed values
        for mname, old_val in old_e.members.items():
            if mname in new_e.members and new_e.members[mname] != old_val:
                changes.append(Change(
                    kind=ChangeKind.ENUM_MEMBER_VALUE_CHANGED,
                    symbol=f"{name}::{mname}",
                    description=(
                        f"Enum member value changed: {name}::{mname} "
                        f"({old_val} → {new_e.members[mname]})"
                    ),
                    old_value=str(old_val),
                    new_value=str(new_e.members[mname]),
                ))

    return changes


# ── Sprint 4: Advanced DWARF (calling convention, toolchain flags, visibility) ─



def _diff_advanced_dwarf(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Sprint 4: calling convention, packing, toolchain flag drift."""
    from .dwarf_advanced import AdvancedDwarfMetadata

    o: AdvancedDwarfMetadata = getattr(old, "dwarf_advanced", None) or AdvancedDwarfMetadata()
    n: AdvancedDwarfMetadata = getattr(new, "dwarf_advanced", None) or AdvancedDwarfMetadata()

    _kind_map = {
        "calling_convention_changed": ChangeKind.CALLING_CONVENTION_CHANGED,
        "value_abi_trait_changed": ChangeKind.VALUE_ABI_TRAIT_CHANGED,
        "struct_packing_changed": ChangeKind.STRUCT_PACKING_CHANGED,
        "toolchain_flag_drift": ChangeKind.TOOLCHAIN_FLAG_DRIFT,
        "type_visibility_changed": ChangeKind.TYPE_VISIBILITY_CHANGED,
        "frame_register_changed": ChangeKind.FRAME_REGISTER_CHANGED,
    }

    return [
        Change(
            kind=_kind_map[kind_str],
            symbol=sym,
            description=desc,
            old_value=old_val,
            new_value=new_val,
        )
        for kind_str, sym, desc, old_val, new_val in diff_advanced_dwarf(o, n)
        if kind_str in _kind_map
    ]


# ── PR #89: ELF fallback for = delete (issue #100) ───────────────────────────

def _diff_elf_deleted_fallback(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """ELF fallback for detecting implicitly-deleted / disappeared symbols.

    When castxml metadata does NOT mark a function as deleted (no ``deleted="1"``)
    but the symbol vanishes from the new library's ELF ``.dynsym`` while still
    being declared in the new snapshot's header model (i.e., it's not FUNC_REMOVED),
    this is strong evidence the function was deleted or made inline without proper
    annotation.

    Detection heuristic:
    1. Function is PUBLIC in old snapshot and present in old ELF ``.dynsym``.
    2. Function is still present in new snapshot (not FUNC_REMOVED) but
       absent from new ELF ``.dynsym``.
    3. Function is not already marked ``is_deleted=True`` (handled by FUNC_DELETED)
       and not already marked ``is_inline=True`` (handled by FUNC_BECAME_INLINE).

    Confidence: 0.75 (lower than FUNC_DELETED castxml path because we're inferring
    from ELF absence rather than explicit annotation).
    """
    changes: list[Change] = []

    old_elf = getattr(old, "elf", None)
    new_elf = getattr(new, "elf", None)

    # Need ELF data on both sides to compare symbol presence
    if old_elf is None or new_elf is None:
        return changes

    old_elf_names: set[str] = {s.name for s in old_elf.symbols}
    new_elf_names: set[str] = {s.name for s in new_elf.symbols}

    # Get all new-snapshot functions keyed by mangled name
    new_func_map = new.function_map

    old_pub = _public_functions(old)

    for mangled, f_old in old_pub.items():
        # Must be present in old ELF (this was a real exported symbol)
        if mangled not in old_elf_names:
            continue

        # Must NOT be present in new ELF (symbol disappeared)
        if mangled in new_elf_names:
            continue

        # Must still be declared in new snapshot (not simply FUNC_REMOVED)
        f_new = new_func_map.get(mangled)
        if f_new is None:
            continue  # Already caught by FUNC_REMOVED — don't double-report

        # Skip if already explicitly marked deleted (FUNC_DELETED handles it)
        if f_new.is_deleted:
            continue

        # Skip if became inline (FUNC_BECAME_INLINE handles it)
        if not f_old.is_inline and f_new.is_inline:
            continue

        # Skip if function moved to hidden visibility — FUNC_VISIBILITY_CHANGED handles it
        if getattr(f_new, "visibility", None) == Visibility.HIDDEN:
            continue

        # Symbol disappeared from ELF without explicit annotation — likely deleted
        changes.append(Change(
            kind=ChangeKind.FUNC_DELETED_ELF_FALLBACK,
            symbol=mangled,
            description=(
                f"Symbol disappeared from ELF .dynsym without explicit deletion marker: "
                f"{f_old.name} — was exported in old library, absent in new library's "
                f"dynamic symbol table while header still declares it"
            ),
            old_value="exported",
            new_value="absent_from_dynsym",
        ))

    return changes


# ── PR #89: Template inner-type deep analysis (issues #38 / #73) ─────────────

def _split_top_level_args(inner: str) -> list[str]:
    """Split a template argument string on top-level commas.

    Respects nested ``<>``, ``()``, ``[]``, and ``{}`` delimiters so that
    types like ``std::function<void(int, double)>`` are not split incorrectly.
    """
    _OPEN = {"<": 0, "(": 1, "[": 2, "{": 3}  # pylint: disable=invalid-name
    _CLOSE = {">": 0, ")": 1, "]": 2, "}": 3}  # pylint: disable=invalid-name

    args: list[str] = []
    current: list[str] = []
    nesting = [0, 0, 0, 0]  # angle, paren, bracket, brace

    for c in inner:
        if c in _OPEN:
            nesting[_OPEN[c]] += 1
            current.append(c)
        elif c == ">" and all(n == 0 for n in nesting[1:]) and nesting[0] > 0:
            nesting[0] -= 1
            current.append(c)
        elif c in _CLOSE and c != ">":
            nesting[_CLOSE[c]] -= 1
            current.append(c)
        elif c == "," and all(n == 0 for n in nesting):
            args.append("".join(current).strip())
            current = []
        else:
            current.append(c)
    if current:
        args.append("".join(current).strip())
    return args


def _extract_template_args(type_str: str) -> list[str] | None:
    """Extract template argument string(s) from a type like ``vector<int>``.

    Returns a list of top-level template arguments (splitting on ``,`` while
    respecting nested ``<>``), or ``None`` if the type is not a template.

    Examples::

        "std::vector<int>"         → ["int"]
        "std::map<int, double>"    → ["int", "double"]
        "Foo<Bar<int>, double>"    → ["Bar<int>", "double"]
        "int"                      → None
        "std::vector<>"            → []
    """
    lt = type_str.find("<")
    if lt == -1:
        return None
    # Find the matching closing >
    depth = 0
    for i, ch in enumerate(type_str[lt:], start=lt):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth == 0:
                inner = type_str[lt + 1 : i].strip()
                if not inner:
                    return []
                return _split_top_level_args(inner)
    return None  # unbalanced brackets — skip


def _template_outer(type_str: str) -> str:
    """Return the outer template name, e.g. ``std::vector`` from ``std::vector<int>``."""
    lt = type_str.find("<")
    return type_str[:lt].rstrip() if lt != -1 else type_str


def _diff_template_inner_types(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect ABI-relevant template inner-type changes in function signatures.

    Compares param types and return types for functions present in both snapshots.
    When both old and new have a template specialization (e.g. ``std::vector<T>``)
    with the *same outer template name* but *different type arguments*, this is an
    ABI break: the instantiation's layout, size, and ABI fingerprint all differ.

    This detector fires in addition to FUNC_PARAMS_CHANGED / FUNC_RETURN_CHANGED
    to provide a more specific, actionable description of the inner-type change.

    Example::

        void process(std::vector<int> v)   →   void process(std::vector<double> v)
        # → TEMPLATE_PARAM_TYPE_CHANGED: "std::vector" inner type int → double

    NOTE on mangling: Under the Itanium C++ ABI, parameter types ARE included in the
    mangled symbol name, so a real ``std::vector<int>`` → ``std::vector<double>`` param
    change produces different mangled names (FUNC_REMOVED + FUNC_ADDED, not an intersection
    hit). This detector therefore only fires for:
      1. Return type template changes (return type is NOT in Itanium mangling for
         non-template functions, so the mangled name stays the same).
      2. Cases where the snapshot was produced with simplified/un-mangled names (e.g.
         from header-only analysis without a compiled .so).
    For production ELF-based snapshots, FUNC_PARAMS_CHANGED is the primary signal.
    """
    changes: list[Change] = []
    old_map = _public_functions(old)
    new_map = _public_functions(new)

    for mangled in set(old_map) & set(new_map):
        f_old = old_map[mangled]
        f_new = new_map[mangled]

        # --- Return type template inner change ---
        old_ret_args = _extract_template_args(f_old.return_type)
        new_ret_args = _extract_template_args(f_new.return_type)
        if (
            old_ret_args is not None
            and new_ret_args is not None
            and old_ret_args != new_ret_args
            and _template_outer(f_old.return_type) == _template_outer(f_new.return_type)
        ):
            changes.append(Change(
                kind=ChangeKind.TEMPLATE_RETURN_TYPE_CHANGED,
                symbol=mangled,
                description=(
                    f"Template return type inner argument changed: {f_old.name} "
                    f"({f_old.return_type} → {f_new.return_type})"
                ),
                old_value=f_old.return_type,
                new_value=f_new.return_type,
            ))

        # --- Param template inner change ---
        for i, (p_old, p_new) in enumerate(zip(f_old.params, f_new.params)):
            old_args = _extract_template_args(p_old.type)
            new_args = _extract_template_args(p_new.type)
            if (
                old_args is not None
                and new_args is not None
                and old_args != new_args
                and _template_outer(p_old.type) == _template_outer(p_new.type)
            ):
                param_label = p_old.name or str(i)
                changes.append(Change(
                    kind=ChangeKind.TEMPLATE_PARAM_TYPE_CHANGED,
                    symbol=mangled,
                    description=(
                        f"Template parameter inner type changed: {f_old.name} "
                        f"param {param_label} ({p_old.type} → {p_new.type})"
                    ),
                    old_value=p_old.type,
                    new_value=p_new.type,
                ))

    return changes
