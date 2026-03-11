"""symbol_diff — Phase 1b diff engine module.

Detects symbol-level changes between two NormalizedSnapshots:
- function added / removed / changed (return type, params, qualifiers)
- variable added / removed / type changed

This module is profile-agnostic — it operates on NormalizedSnapshot
and returns generic Change objects. Language profile classification
happens downstream (between diff and suppress).

Pipeline position: corpus → **diff** → suppress → policy
"""
from __future__ import annotations

from abicheck.model import Function, Variable, Visibility
from abicheck.core.corpus.normalizer import NormalizedSnapshot
from abicheck.core.model import (
    Change,
    ChangeKind,
    ChangeSeverity,
    EntitySnapshot,
    Origin,
)


def _func_snapshot(f: Function) -> EntitySnapshot:
    params_repr = ", ".join(f"{p.type} {p.name}".strip() for p in f.params)
    return EntitySnapshot(
        entity_repr=f"{f.return_type} {f.name}({params_repr})",
        raw={
            "return_type": f.return_type,
            "params": [{"name": p.name, "type": p.type} for p in f.params],
            "is_virtual": f.is_virtual,
            "is_noexcept": f.is_noexcept,
            "visibility": f.visibility.value,
        },
    )


def _var_snapshot(v: Variable) -> EntitySnapshot:
    return EntitySnapshot(
        entity_repr=f"{v.type} {v.name}",
        raw={"type": v.type, "visibility": v.visibility.value},
    )


def diff_symbols(
    before: NormalizedSnapshot,
    after: NormalizedSnapshot,
) -> list[Change]:
    """Detect all symbol-level changes between two snapshots.

    Returns a list of Change objects. Caller is responsible for
    applying suppression and policy classification.
    """
    changes: list[Change] = []
    changes.extend(_diff_functions(before, after))
    changes.extend(_diff_variables(before, after))
    return changes


def _diff_functions(
    before: NormalizedSnapshot,
    after: NormalizedSnapshot,
) -> list[Change]:
    changes: list[Change] = []

    before_pub = {
        m: f for m, f in before.func_index.items()
        if f.visibility == Visibility.PUBLIC
    }
    after_pub = {
        m: f for m, f in after.func_index.items()
        if f.visibility == Visibility.PUBLIC
    }

    before_keys = set(before_pub)
    after_keys = set(after_pub)

    # Removed symbols
    for mangled in before_keys - after_keys:
        f = before_pub[mangled]
        changes.append(Change(
            change_kind=ChangeKind.SYMBOL,
            entity_type="function",
            entity_name=f.name,
            before=_func_snapshot(f),
            after=EntitySnapshot(entity_repr="<removed>"),
            severity=ChangeSeverity.BREAK,
            origin=Origin.ELF,
            confidence=0.95,
        ))

    # Added symbols (compatible extension)
    for mangled in after_keys - before_keys:
        f = after_pub[mangled]
        changes.append(Change(
            change_kind=ChangeKind.SYMBOL,
            entity_type="function",
            entity_name=f.name,
            before=EntitySnapshot(entity_repr="<absent>"),
            after=_func_snapshot(f),
            severity=ChangeSeverity.COMPATIBLE_EXTENSION,
            origin=Origin.ELF,
            confidence=0.95,
        ))

    # Changed symbols (present in both — check signature)
    for mangled in before_keys & after_keys:
        f_old = before_pub[mangled]
        f_new = after_pub[mangled]
        sub = _diff_function_pair(f_old, f_new)
        changes.extend(sub)

    return changes


def _diff_function_pair(f_old: Function, f_new: Function) -> list[Change]:
    changes: list[Change] = []
    snap_old = _func_snapshot(f_old)
    snap_new = _func_snapshot(f_new)

    # Return type change
    if f_old.return_type != f_new.return_type:
        changes.append(Change(
            change_kind=ChangeKind.SYMBOL,
            entity_type="function",
            entity_name=f_old.name,
            before=snap_old,
            after=snap_new,
            severity=ChangeSeverity.BREAK,
            origin=Origin.CASTXML,
            confidence=0.9,
        ))

    # Parameter count / type change
    elif len(f_old.params) != len(f_new.params) or any(
        p_old.type != p_new.type
        for p_old, p_new in zip(f_old.params, f_new.params)
    ):
        changes.append(Change(
            change_kind=ChangeKind.SYMBOL,
            entity_type="function",
            entity_name=f_old.name,
            before=snap_old,
            after=snap_new,
            severity=ChangeSeverity.BREAK,
            origin=Origin.CASTXML,
            confidence=0.9,
        ))

    # noexcept removed → breaking (callers may not catch exceptions)
    elif f_old.is_noexcept and not f_new.is_noexcept:
        changes.append(Change(
            change_kind=ChangeKind.SYMBOL,
            entity_type="function",
            entity_name=f_old.name,
            before=snap_old,
            after=snap_new,
            severity=ChangeSeverity.BREAK,
            origin=Origin.CASTXML,
            confidence=0.85,
        ))

    return changes


def _diff_variables(
    before: NormalizedSnapshot,
    after: NormalizedSnapshot,
) -> list[Change]:
    changes: list[Change] = []

    before_pub = {
        m: v for m, v in before.var_index.items()
        if v.visibility == Visibility.PUBLIC
    }
    after_pub = {
        m: v for m, v in after.var_index.items()
        if v.visibility == Visibility.PUBLIC
    }

    for mangled in set(before_pub) - set(after_pub):
        v = before_pub[mangled]
        changes.append(Change(
            change_kind=ChangeKind.SYMBOL,
            entity_type="variable",
            entity_name=v.name,
            before=_var_snapshot(v),
            after=EntitySnapshot(entity_repr="<removed>"),
            severity=ChangeSeverity.BREAK,
            origin=Origin.ELF,
            confidence=0.9,
        ))

    for mangled in set(after_pub) - set(before_pub):
        v = after_pub[mangled]
        changes.append(Change(
            change_kind=ChangeKind.SYMBOL,
            entity_type="variable",
            entity_name=v.name,
            before=EntitySnapshot(entity_repr="<absent>"),
            after=_var_snapshot(v),
            severity=ChangeSeverity.COMPATIBLE_EXTENSION,
            origin=Origin.ELF,
            confidence=0.9,
        ))

    for mangled in set(before_pub) & set(after_pub):
        v_old = before_pub[mangled]
        v_new = after_pub[mangled]
        if v_old.type != v_new.type:
            changes.append(Change(
                change_kind=ChangeKind.SYMBOL,
                entity_type="variable",
                entity_name=v_old.name,
                before=_var_snapshot(v_old),
                after=_var_snapshot(v_new),
                severity=ChangeSeverity.BREAK,
                origin=Origin.CASTXML,
                confidence=0.85,
            ))

    return changes
