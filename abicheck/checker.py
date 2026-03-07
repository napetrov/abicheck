"""Checker — diff two AbiSnapshots, classify changes, produce a verdict."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from .model import AbiSnapshot, Function, Visibility


class ChangeKind(str, Enum):
    # Function / variable changes
    FUNC_REMOVED = "func_removed"        # public symbol removed → BREAKING
    FUNC_ADDED = "func_added"            # new public symbol → COMPATIBLE
    FUNC_RETURN_CHANGED = "func_return_changed"   # return type changed → BREAKING
    FUNC_PARAMS_CHANGED = "func_params_changed"   # parameter types changed → BREAKING
    FUNC_NOEXCEPT_ADDED = "func_noexcept_added"   # noexcept added → SOURCE_BREAK (ABI-safe in most ABIs, but source-level narrowing)
    FUNC_NOEXCEPT_REMOVED = "func_noexcept_removed"  # noexcept removed → BREAKING (can widen exception spec)
    FUNC_VIRTUAL_ADDED = "func_virtual_added"    # became virtual → vtable change → BREAKING
    FUNC_VIRTUAL_REMOVED = "func_virtual_removed"  # → BREAKING

    VAR_REMOVED = "var_removed"
    VAR_ADDED = "var_added"
    VAR_TYPE_CHANGED = "var_type_changed"

    # Type changes
    TYPE_SIZE_CHANGED = "type_size_changed"      # struct/class layout change → BREAKING
    TYPE_ALIGNMENT_CHANGED = "type_alignment_changed"  # alignment change → BREAKING
    TYPE_FIELD_REMOVED = "type_field_removed"    # → BREAKING
    TYPE_FIELD_ADDED = "type_field_added"        # if in non-final class, may be BREAKING
    TYPE_FIELD_OFFSET_CHANGED = "type_field_offset_changed"  # → BREAKING
    TYPE_FIELD_TYPE_CHANGED = "type_field_type_changed"      # → BREAKING
    TYPE_BASE_CHANGED = "type_base_changed"      # inheritance change → BREAKING
    TYPE_VTABLE_CHANGED = "type_vtable_changed"  # → BREAKING

    TYPE_ADDED = "type_added"                    # new type → COMPATIBLE
    TYPE_REMOVED = "type_removed"                # type removed → BREAKING if used in API
    TYPE_FIELD_ADDED_COMPATIBLE = "type_field_added_compatible"  # appended to standard-layout non-polymorphic type


class Verdict(str, Enum):
    NO_CHANGE = "NO_CHANGE"         # identical ABI
    COMPATIBLE = "COMPATIBLE"       # only additions
    SOURCE_BREAK = "SOURCE_BREAK"   # source-level break, binary compatible
    BREAKING = "BREAKING"           # binary ABI break


# Which ChangeKinds are immediately BREAKING
_BREAKING_KINDS = {
    ChangeKind.FUNC_REMOVED,
    ChangeKind.FUNC_RETURN_CHANGED,
    ChangeKind.FUNC_PARAMS_CHANGED,
    ChangeKind.FUNC_NOEXCEPT_REMOVED,
    ChangeKind.FUNC_VIRTUAL_ADDED,
    ChangeKind.FUNC_VIRTUAL_REMOVED,
    ChangeKind.VAR_REMOVED,
    ChangeKind.VAR_TYPE_CHANGED,
    ChangeKind.TYPE_SIZE_CHANGED,
    ChangeKind.TYPE_ALIGNMENT_CHANGED,
    ChangeKind.TYPE_FIELD_REMOVED,
    ChangeKind.TYPE_FIELD_OFFSET_CHANGED,
    ChangeKind.TYPE_FIELD_TYPE_CHANGED,
    ChangeKind.TYPE_BASE_CHANGED,
    ChangeKind.TYPE_VTABLE_CHANGED,
    ChangeKind.TYPE_REMOVED,
    ChangeKind.FUNC_NOEXCEPT_ADDED,  # C++17: noexcept is part of the function type (P0012R1)
    ChangeKind.TYPE_FIELD_ADDED,  # for polymorphic / non-standard-layout types
}

_SOURCE_BREAK_KINDS: set = set()  # reserved for future source-only breaks


_COMPATIBLE_KINDS = {
    ChangeKind.FUNC_ADDED,
    ChangeKind.VAR_ADDED,
    ChangeKind.TYPE_ADDED,
    # TYPE_FIELD_ADDED intentionally omitted: compatible only for standard-layout
    # non-polymorphic types; context-aware verdict set in _diff_types()
    ChangeKind.TYPE_FIELD_ADDED_COMPATIBLE,
}


@dataclass
class Change:
    kind: ChangeKind
    symbol: str               # mangled name or type name
    description: str          # human-readable
    old_value: str | None = None
    new_value: str | None = None


@dataclass
class DiffResult:
    old_version: str
    new_version: str
    library: str
    changes: list[Change] = field(default_factory=list)
    verdict: Verdict = Verdict.NO_CHANGE

    @property
    def breaking(self) -> list[Change]:
        return [c for c in self.changes if c.kind in _BREAKING_KINDS]

    @property
    def source_breaks(self) -> list[Change]:
        return [c for c in self.changes if c.kind in _SOURCE_BREAK_KINDS]

    @property
    def compatible(self) -> list[Change]:
        return [c for c in self.changes if c.kind in _COMPATIBLE_KINDS]


def _public(funcs) -> list[Function]:
    return [f for f in funcs if f.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)]


def _diff_functions(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    changes: list[Change] = []
    old_map = {k: v for k, v in old.function_map.items() if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)}
    new_map = {k: v for k, v in new.function_map.items() if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)}

    for mangled, f_old in old_map.items():
        if mangled not in new_map:
            changes.append(Change(
                kind=ChangeKind.FUNC_REMOVED,
                symbol=mangled,
                description=f"Public function removed: {f_old.name}",
                old_value=f_old.name,
            ))
            continue
        f_new = new_map[mangled]

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

    for mangled, f_new in new_map.items():
        if mangled not in old_map:
            changes.append(Change(
                kind=ChangeKind.FUNC_ADDED,
                symbol=mangled,
                description=f"New public function: {f_new.name}",
                new_value=f_new.name,
            ))

    return changes


def _diff_variables(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    changes: list[Change] = []
    old_map = {k: v for k, v in old.variable_map.items() if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)}
    new_map = {k: v for k, v in new.variable_map.items() if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)}

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
    old_map = {t.name: t for t in old.types}
    new_map = {t.name: t for t in new.types}

    for name, t_old in old_map.items():
        if name not in new_map:
            changes.append(Change(
                kind=ChangeKind.TYPE_REMOVED,
                symbol=name,
                description=f"Type removed: {name}",
            ))
            continue
        t_new = new_map[name]

        if t_old.size_bits is not None and t_new.size_bits is not None:
            if t_old.size_bits != t_new.size_bits:
                changes.append(Change(
                    kind=ChangeKind.TYPE_SIZE_CHANGED,
                    symbol=name,
                    description=f"Size changed: {name} ({t_old.size_bits} → {t_new.size_bits} bits)",
                    old_value=str(t_old.size_bits),
                    new_value=str(t_new.size_bits),
                ))

        if t_old.alignment_bits is not None and t_new.alignment_bits is not None:
            if t_old.alignment_bits != t_new.alignment_bits:
                changes.append(Change(
                    kind=ChangeKind.TYPE_ALIGNMENT_CHANGED,
                    symbol=name,
                    description=f"Alignment changed: {name} ({t_old.alignment_bits} → {t_new.alignment_bits} bits)",
                    old_value=str(t_old.alignment_bits),
                    new_value=str(t_new.alignment_bits),
                ))

        old_fields = {f.name: f for f in t_old.fields}
        new_fields = {f.name: f for f in t_new.fields}

        for fname, f_old in old_fields.items():
            if fname not in new_fields:
                changes.append(Change(
                    kind=ChangeKind.TYPE_FIELD_REMOVED,
                    symbol=name,
                    description=f"Field removed: {name}::{fname}",
                ))
            else:
                f_new = new_fields[fname]
                if f_old.type != f_new.type:
                    changes.append(Change(
                        kind=ChangeKind.TYPE_FIELD_TYPE_CHANGED,
                        symbol=name,
                        description=f"Field type changed: {name}::{fname}",
                        old_value=f_old.type, new_value=f_new.type,
                    ))
                if (f_old.offset_bits is not None and f_new.offset_bits is not None
                        and f_old.offset_bits != f_new.offset_bits):
                    changes.append(Change(
                        kind=ChangeKind.TYPE_FIELD_OFFSET_CHANGED,
                        symbol=name,
                        description=f"Field offset changed: {name}::{fname} ({f_old.offset_bits} → {f_new.offset_bits} bits)",
                        old_value=str(f_old.offset_bits), new_value=str(f_new.offset_bits),
                    ))

        for fname in new_fields:
            if fname not in old_fields:
                # Field addition is BREAKING for polymorphic types or types with vtables;
                # COMPATIBLE only for standard-layout types without virtual functions
                is_polymorphic = bool(t_new.vtable or t_new.virtual_bases)
                field_kind = (
                    ChangeKind.TYPE_FIELD_ADDED_COMPATIBLE
                    if not is_polymorphic and t_new.kind in ("struct", "union")
                    else ChangeKind.TYPE_FIELD_ADDED  # BREAKING
                )
                changes.append(Change(
                    kind=field_kind,
                    symbol=name,
                    description=f"Field added: {name}::{fname}",
                ))

        if t_old.bases != t_new.bases or t_old.virtual_bases != t_new.virtual_bases:
            changes.append(Change(
                kind=ChangeKind.TYPE_BASE_CHANGED,
                symbol=name,
                description=f"Base classes changed: {name}",
                old_value=str(t_old.bases), new_value=str(t_new.bases),
            ))
        else:
            # Detect non-virtual base promoted to virtual (changes VTT layout).
            # Only runs when bases/virtual_bases are unchanged as sets but virtualness differs.
            old_all_bases = set(t_old.bases) | set(t_old.virtual_bases)
            new_all_bases = set(t_new.bases) | set(t_new.virtual_bases)
            if old_all_bases == new_all_bases:
                old_virt = set(t_old.virtual_bases)
                new_virt = set(t_new.virtual_bases)
                if old_virt != new_virt:
                    changes.append(Change(
                        kind=ChangeKind.TYPE_BASE_CHANGED,
                        symbol=name,
                        description=f"Virtual inheritance changed: {name} (affects VTT layout)",
                        old_value=f"virtual={sorted(old_virt)}",
                        new_value=f"virtual={sorted(new_virt)}",
                    ))

        if t_old.vtable != t_new.vtable:
            if Counter(t_old.vtable) == Counter(t_new.vtable) and t_old.vtable != t_new.vtable:
                # Same entries, different order — reorder is still BREAKING
                description = f"vtable reordered: {name}"
            else:
                description = f"vtable changed: {name}"
            changes.append(Change(
                kind=ChangeKind.TYPE_VTABLE_CHANGED,
                symbol=name,
                description=description,
            ))

    for name in new_map:
        if name not in old_map:
            changes.append(Change(
                kind=ChangeKind.TYPE_ADDED,
                symbol=name,
                description=f"New type: {name}",
            ))

    return changes


def _compute_verdict(changes: list[Change]) -> Verdict:
    if not changes:
        return Verdict.NO_CHANGE
    kinds = {c.kind for c in changes}
    if kinds & _BREAKING_KINDS:
        return Verdict.BREAKING
    if kinds & _SOURCE_BREAK_KINDS:
        return Verdict.SOURCE_BREAK
    return Verdict.COMPATIBLE


def compare(old: AbiSnapshot, new: AbiSnapshot) -> DiffResult:
    """Diff two AbiSnapshots and return a DiffResult with verdict."""
    changes: list[Change] = []
    changes.extend(_diff_functions(old, new))
    changes.extend(_diff_variables(old, new))
    changes.extend(_diff_types(old, new))
    verdict = _compute_verdict(changes)
    return DiffResult(
        old_version=old.version,
        new_version=new.version,
        library=old.library,
        changes=changes,
        verdict=verdict,
    )
