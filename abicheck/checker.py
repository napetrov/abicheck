"""Checker — diff two AbiSnapshots, classify changes, produce a verdict."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from .dwarf_advanced import diff_advanced_dwarf
from .elf_metadata import SymbolBinding, SymbolType
from .model import AccessLevel, AbiSnapshot, EnumType, Function, Param, RecordType, TypeField, Visibility

if TYPE_CHECKING:
    from .suppression import SuppressionList


class ChangeKind(str, Enum):
    # Function / variable changes
    FUNC_REMOVED = "func_removed"        # public symbol removed → BREAKING
    FUNC_ADDED = "func_added"            # new public symbol → COMPATIBLE
    FUNC_RETURN_CHANGED = "func_return_changed"   # return type changed → BREAKING
    FUNC_PARAMS_CHANGED = "func_params_changed"   # parameter types changed → BREAKING
    FUNC_NOEXCEPT_ADDED = "func_noexcept_added"   # noexcept added → BREAKING (C++17 P0012R1: noexcept is part of function type)
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

    # Enum changes
    ENUM_MEMBER_REMOVED = "enum_member_removed"
    ENUM_MEMBER_ADDED = "enum_member_added"  # BREAKING (closed enums / value shift risk)
    ENUM_MEMBER_VALUE_CHANGED = "enum_member_value_changed"
    ENUM_LAST_MEMBER_VALUE_CHANGED = "enum_last_member_value_changed"  # sentinel changed
    TYPEDEF_REMOVED = "typedef_removed"  # placed here for logical grouping

    # Method qualifier changes
    FUNC_STATIC_CHANGED = "func_static_changed"
    FUNC_CV_CHANGED = "func_cv_changed"  # const/volatile on this
    FUNC_VISIBILITY_CHANGED = "func_visibility_changed"  # default→hidden: symbol gone from ABI

    # Virtual changes
    FUNC_PURE_VIRTUAL_ADDED = "func_pure_virtual_added"
    FUNC_VIRTUAL_BECAME_PURE = "func_virtual_became_pure"

    # Union field changes
    UNION_FIELD_ADDED = "union_field_added"
    UNION_FIELD_REMOVED = "union_field_removed"
    UNION_FIELD_TYPE_CHANGED = "union_field_type_changed"

    # Typedef changes
    TYPEDEF_BASE_CHANGED = "typedef_base_changed"

    # Bitfield changes
    FIELD_BITFIELD_CHANGED = "field_bitfield_changed"

    # ── ELF-only (Sprint 2) ──────────────────────────────────────────────
    # Dynamic section contract
    SONAME_CHANGED = "soname_changed"
    NEEDED_ADDED = "needed_added"            # new DT_NEEDED dep
    NEEDED_REMOVED = "needed_removed"          # dep dropped
    RPATH_CHANGED = "rpath_changed"
    RUNPATH_CHANGED = "runpath_changed"

    # Symbol metadata drift (ELF .dynsym)
    SYMBOL_BINDING_CHANGED = "symbol_binding_changed"      # GLOBAL→WEAK (breaking)
    SYMBOL_BINDING_STRENGTHENED = "symbol_binding_strengthened"  # WEAK→GLOBAL (compatible)
    SYMBOL_TYPE_CHANGED = "symbol_type_changed"     # FUNC→OBJECT, etc.
    SYMBOL_SIZE_CHANGED = "symbol_size_changed"     # st_size changed
    IFUNC_INTRODUCED = "ifunc_introduced"        # → STT_GNU_IFUNC
    IFUNC_REMOVED = "ifunc_removed"           # STT_GNU_IFUNC →
    COMMON_SYMBOL_RISK = "common_symbol_risk"      # STT_COMMON exported

    # Symbol versioning contract
    SYMBOL_VERSION_DEFINED_REMOVED = "symbol_version_defined_removed"
    SYMBOL_VERSION_REQUIRED_ADDED = "symbol_version_required_added"   # new GLIBC_X
    SYMBOL_VERSION_REQUIRED_REMOVED = "symbol_version_required_removed"

    # DWARF layout (Sprint 3)
    DWARF_INFO_MISSING = "dwarf_info_missing"         # new binary stripped of -g
    STRUCT_SIZE_CHANGED = "struct_size_changed"        # sizeof(T) changed
    STRUCT_FIELD_OFFSET_CHANGED = "struct_field_offset_changed" # field moved
    STRUCT_FIELD_REMOVED = "struct_field_removed"       # field deleted
    STRUCT_FIELD_TYPE_CHANGED = "struct_field_type_changed"  # field type/size changed
    STRUCT_ALIGNMENT_CHANGED = "struct_alignment_changed"   # alignof(T) changed
    ENUM_UNDERLYING_SIZE_CHANGED = "enum_underlying_size_changed"  # int→long

    # DWARF advanced (Sprint 4)
    CALLING_CONVENTION_CHANGED = "calling_convention_changed"   # DW_AT_calling_convention drift
    STRUCT_PACKING_CHANGED = "struct_packing_changed"       # __attribute__((packed)) added/removed
    TYPE_VISIBILITY_CHANGED = "type_visibility_changed"      # typeinfo/vtable visibility changed
    TOOLCHAIN_FLAG_DRIFT = "toolchain_flag_drift"         # -fshort-enums/-fpack-struct drift

    # Sprint 2 — gap detectors
    FUNC_DELETED = "func_deleted"                        # = delete added → BREAKING (was callable)
    VAR_BECAME_CONST = "var_became_const"                # non-const → const: writes → SIGSEGV
    VAR_LOST_CONST = "var_lost_const"                    # const → non-const: BREAKING (ODR / inlining)
    TYPE_BECAME_OPAQUE = "type_became_opaque"            # complete → forward-decl only → BREAKING
    BASE_CLASS_POSITION_CHANGED = "base_class_position_changed"  # base reorder → this-ptr offset change
    BASE_CLASS_VIRTUAL_CHANGED = "base_class_virtual_changed"    # base became virtual or non-virtual

    # ── Sprint 7 — Full ABICC parity + beyond ────────────────────────────
    # Source-level breaks (not binary ABI, but API contract)
    ENUM_MEMBER_RENAMED = "enum_member_renamed"              # same value, different name → SOURCE_BREAK
    PARAM_DEFAULT_VALUE_CHANGED = "param_default_value_changed"  # default arg changed
    PARAM_DEFAULT_VALUE_REMOVED = "param_default_value_removed"  # default arg removed → SOURCE_BREAK
    FIELD_RENAMED = "field_renamed"                          # same offset+type, different name
    PARAM_RENAMED = "param_renamed"                          # parameter name changed

    # Field qualifier changes
    FIELD_BECAME_CONST = "field_became_const"
    FIELD_LOST_CONST = "field_lost_const"
    FIELD_BECAME_VOLATILE = "field_became_volatile"
    FIELD_LOST_VOLATILE = "field_lost_volatile"
    FIELD_BECAME_MUTABLE = "field_became_mutable"
    FIELD_LOST_MUTABLE = "field_lost_mutable"

    # Pointer level changes
    PARAM_POINTER_LEVEL_CHANGED = "param_pointer_level_changed"      # T* → T** or T** → T*
    RETURN_POINTER_LEVEL_CHANGED = "return_pointer_level_changed"    # return T* → T**

    # Access level changes
    METHOD_ACCESS_CHANGED = "method_access_changed"          # public→protected/private
    FIELD_ACCESS_CHANGED = "field_access_changed"            # public→private field

    # Anonymous struct/union
    ANON_FIELD_CHANGED = "anon_field_changed"                # anon struct/union member changed


class Verdict(str, Enum):
    NO_CHANGE = "NO_CHANGE"         # identical ABI
    COMPATIBLE = "COMPATIBLE"       # only additions
    SOURCE_BREAK = "SOURCE_BREAK"   # source-level break, binary compatible
    BREAKING = "BREAKING"           # binary ABI break


# Which ChangeKinds are immediately BREAKING (binary ABI incompatibility)
_BREAKING_KINDS = {
    ChangeKind.FUNC_REMOVED,
    ChangeKind.FUNC_RETURN_CHANGED,
    ChangeKind.FUNC_PARAMS_CHANGED,
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
    ChangeKind.TYPE_FIELD_ADDED,  # for polymorphic / non-standard-layout types
    ChangeKind.ENUM_MEMBER_REMOVED,
    ChangeKind.ENUM_MEMBER_VALUE_CHANGED,
    ChangeKind.ENUM_LAST_MEMBER_VALUE_CHANGED,
    ChangeKind.FUNC_STATIC_CHANGED,
    ChangeKind.FUNC_CV_CHANGED,
    ChangeKind.FUNC_VISIBILITY_CHANGED,
    ChangeKind.FUNC_PURE_VIRTUAL_ADDED,
    ChangeKind.FUNC_VIRTUAL_BECAME_PURE,
    ChangeKind.UNION_FIELD_REMOVED,
    ChangeKind.UNION_FIELD_TYPE_CHANGED,
    ChangeKind.TYPEDEF_BASE_CHANGED,
    ChangeKind.TYPEDEF_REMOVED,
    ChangeKind.FIELD_BITFIELD_CHANGED,
    # ELF Sprint 2
    ChangeKind.SONAME_CHANGED,
    ChangeKind.SYMBOL_TYPE_CHANGED,
    ChangeKind.SYMBOL_SIZE_CHANGED,           # in ELF-only mode (no headers/DWARF) this may be
                                              # the sole signal for vtable/variable layout changes
    ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED,
    ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED, # library fails to load on runtimes lacking the version
    # DWARF Sprint 3 + 4
    ChangeKind.STRUCT_SIZE_CHANGED,
    ChangeKind.STRUCT_FIELD_OFFSET_CHANGED,
    ChangeKind.STRUCT_FIELD_REMOVED,
    ChangeKind.STRUCT_FIELD_TYPE_CHANGED,
    ChangeKind.STRUCT_ALIGNMENT_CHANGED,
    ChangeKind.ENUM_UNDERLYING_SIZE_CHANGED,
    ChangeKind.CALLING_CONVENTION_CHANGED,
    ChangeKind.STRUCT_PACKING_CHANGED,
    # Sprint 2 — gap detectors
    ChangeKind.FUNC_DELETED,
    ChangeKind.VAR_BECAME_CONST,              # writes → SIGSEGV when variable moves to .rodata
    ChangeKind.VAR_LOST_CONST,                # ODR / inlining break; callers may have cached const value
    ChangeKind.TYPE_BECAME_OPAQUE,
    ChangeKind.BASE_CLASS_POSITION_CHANGED,
    ChangeKind.BASE_CLASS_VIRTUAL_CHANGED,
    # DWARF Sprint 4
    ChangeKind.TYPE_VISIBILITY_CHANGED,       # cross-DSO dynamic_cast / exception matching can fail
    # Sprint 7 — pointer level changes are binary ABI breaks
    ChangeKind.PARAM_POINTER_LEVEL_CHANGED,
    ChangeKind.RETURN_POINTER_LEVEL_CHANGED,
    ChangeKind.ANON_FIELD_CHANGED,
}

_COMPATIBLE_KINDS: set[ChangeKind] = {
    # Header/API additions
    ChangeKind.FUNC_ADDED,
    ChangeKind.VAR_ADDED,
    ChangeKind.TYPE_ADDED,
    # TYPE_FIELD_ADDED intentionally omitted: compatible only for standard-layout
    # non-polymorphic types; context-aware verdict set in _diff_types()
    ChangeKind.TYPE_FIELD_ADDED_COMPATIBLE,

    # noexcept changes: Itanium ABI mangling does not change in practice;
    # existing binaries resolve the same symbol.  Source-level concern only
    # (C++17 function-pointer type system), not a binary ABI break.
    ChangeKind.FUNC_NOEXCEPT_ADDED,
    ChangeKind.FUNC_NOEXCEPT_REMOVED,

    # Enum member addition: existing compiled enum values are unchanged;
    # new enumerator does not shift others.  Source-level switch coverage
    # concern, not binary ABI.  Value shifts are caught separately by
    # ENUM_MEMBER_VALUE_CHANGED.
    ChangeKind.ENUM_MEMBER_ADDED,

    # Union field addition: all fields start at offset 0; existing fields
    # are unaffected.  Size increase (if any) is caught by TYPE_SIZE_CHANGED.
    ChangeKind.UNION_FIELD_ADDED,

    # ELF-only warning/compatible drift
    ChangeKind.NEEDED_ADDED,              # new dep: may not exist on older systems — warn, not hard-break
    ChangeKind.NEEDED_REMOVED,            # removing a dep is compatible (but deployment risk)
    ChangeKind.RUNPATH_CHANGED,           # search path drift — warn only
    ChangeKind.RPATH_CHANGED,
    ChangeKind.COMMON_SYMBOL_RISK,        # STT_COMMON — risk, not proven break
    ChangeKind.SYMBOL_VERSION_REQUIRED_REMOVED,
    ChangeKind.SYMBOL_BINDING_STRENGTHENED,  # WEAK→GLOBAL: backward-compatible for most consumers

    # GLOBAL→WEAK: symbol still exported and resolvable by the dynamic
    # linker; interposition semantics change but existing binaries work.
    ChangeKind.SYMBOL_BINDING_CHANGED,

    # GNU IFUNC ↔ regular function: transparent to callers; the PLT/GOT
    # mechanism handles resolution.  This is an implementation optimization.
    ChangeKind.IFUNC_INTRODUCED,
    ChangeKind.IFUNC_REMOVED,

    # DWARF diagnostics (comparison coverage gap warning)
    ChangeKind.DWARF_INFO_MISSING,
    ChangeKind.TOOLCHAIN_FLAG_DRIFT,  # informational — not a proven binary break

    # Sprint 7 — field qualifier changes are informational (compatible)
    ChangeKind.FIELD_BECAME_CONST,
    ChangeKind.FIELD_LOST_CONST,
    ChangeKind.FIELD_BECAME_VOLATILE,
    ChangeKind.FIELD_LOST_VOLATILE,
    ChangeKind.FIELD_BECAME_MUTABLE,
    ChangeKind.FIELD_LOST_MUTABLE,
    ChangeKind.PARAM_DEFAULT_VALUE_CHANGED,  # informational, not binary break
}

_SOURCE_BREAK_KINDS: set[ChangeKind] = {
    # Source-level breaks: code won't compile but existing binaries are fine
    ChangeKind.ENUM_MEMBER_RENAMED,
    ChangeKind.PARAM_DEFAULT_VALUE_REMOVED,
    ChangeKind.FIELD_RENAMED,
    ChangeKind.PARAM_RENAMED,
    ChangeKind.METHOD_ACCESS_CHANGED,
    ChangeKind.FIELD_ACCESS_CHANGED,
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
    suppressed_count: int = 0
    suppressed_changes: list[Change] = field(default_factory=list)  # full audit trail
    suppression_file_provided: bool = False  # True when --suppress was passed, even if 0 matched

    @property
    def breaking(self) -> list[Change]:
        return [c for c in self.changes if c.kind in _BREAKING_KINDS]

    @property
    def source_breaks(self) -> list[Change]:
        return [c for c in self.changes if c.kind in _SOURCE_BREAK_KINDS]

    @property
    def compatible(self) -> list[Change]:
        return [c for c in self.changes if c.kind in _COMPATIBLE_KINDS]


def _diff_functions(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    changes: list[Change] = []
    old_map = {k: v for k, v in old.function_map.items() if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)}
    new_map = {k: v for k, v in new.function_map.items() if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)}

    # Build a lookup of ALL functions in new snapshot (including hidden).
    # When dump() uses castxml headers, _CastxmlParser._visibility() assigns
    # Visibility.HIDDEN to functions present in XML but absent from .dynsym —
    # so new_all correctly contains hidden functions in the castxml path.
    # ELF_ONLY→HIDDEN is also treated as FUNC_VISIBILITY_CHANGED: callers
    # that resolved the symbol dynamically will still break.
    new_all = new.function_map

    for mangled, f_old in old_map.items():
        if mangled not in new_map:
            # Check if it moved to hidden visibility (not truly removed)
            f_hidden = new_all.get(mangled)
            if f_hidden is not None and f_hidden.visibility == Visibility.HIDDEN:
                changes.append(Change(
                    kind=ChangeKind.FUNC_VISIBILITY_CHANGED,
                    symbol=mangled,
                    description=f"Function visibility changed to hidden: {f_old.name}",
                    old_value=f_old.visibility.value,
                    new_value=f_hidden.visibility.value,
                ))
            else:
                changes.append(Change(
                    kind=ChangeKind.FUNC_REMOVED,
                    symbol=mangled,
                    description=f"{f_old.visibility.value.capitalize()} function removed: {f_old.name}",
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

    # FUNC_DELETED: function was not deleted before, now marked = delete
    # Use all-functions maps (not just public) to catch deleted declarations
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
    lost_virtual   = (old_virt_set - new_virt_set) & new_bases_set
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

        for mname, mval in old_members.items():
            if mname not in new_members:
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

        for mname, mval in new_members.items():
            if mname not in old_members:
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
    vis = (Visibility.PUBLIC, Visibility.ELF_ONLY)
    old_by_mangled = {k: v for k, v in old.function_map.items() if v.visibility in vis}
    new_by_mangled = {k: v for k, v in new.function_map.items() if v.visibility in vis}

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


def _diff_typedefs(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    changes: list[Change] = []
    for alias, old_type in old.typedefs.items():
        new_type = new.typedefs.get(alias)
        if new_type is None:
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
        old_by_val: dict[int, str] = {m.value: m.name for m in e_old.members}
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
    vis = (Visibility.PUBLIC, Visibility.ELF_ONLY)
    old_map = {k: v for k, v in old.function_map.items() if v.visibility in vis}
    new_map = {k: v for k, v in new.function_map.items() if v.visibility in vis}

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
    vis = (Visibility.PUBLIC, Visibility.ELF_ONLY)
    old_map = {k: v for k, v in old.function_map.items() if v.visibility in vis}
    new_map = {k: v for k, v in new.function_map.items() if v.visibility in vis}

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
    vis = (Visibility.PUBLIC, Visibility.ELF_ONLY)
    old_map = {k: v for k, v in old.function_map.items() if v.visibility in vis}
    new_map = {k: v for k, v in new.function_map.items() if v.visibility in vis}

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


def _diff_access_levels(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect access level changes on methods and fields."""
    changes: list[Change] = []

    # Method access changes
    vis = (Visibility.PUBLIC, Visibility.ELF_ONLY)
    old_map = {k: v for k, v in old.function_map.items() if v.visibility in vis}
    new_map = {k: v for k, v in new.function_map.items() if v.visibility in vis}

    for mangled, f_old in old_map.items():
        f_new = new_map.get(mangled)
        if f_new is None:
            continue
        if f_old.access != f_new.access:
            changes.append(Change(
                kind=ChangeKind.METHOD_ACCESS_CHANGED,
                symbol=mangled,
                description=f"Method access level changed: {f_old.name} ({f_old.access.value} → {f_new.access.value})",
                old_value=f_old.access.value,
                new_value=f_new.access.value,
            ))

    # Field access changes
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
            if f_old_f.access != f_new_f.access:
                changes.append(Change(
                    kind=ChangeKind.FIELD_ACCESS_CHANGED,
                    symbol=name,
                    description=f"Field access level changed: {name}::{fname} ({f_old_f.access.value} → {f_new_f.access.value})",
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

    all_req_libs = set(old_elf.versions_required) | set(new_elf.versions_required)
    for lib in sorted(all_req_libs):
        old_vers = set(old_elf.versions_required.get(lib, []))
        new_vers = set(new_elf.versions_required.get(lib, []))
        for ver in sorted(new_vers - old_vers):
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


def _compute_verdict(changes: list[Change]) -> Verdict:
    if not changes:
        return Verdict.NO_CHANGE
    kinds = {c.kind for c in changes}
    if kinds & _BREAKING_KINDS:
        return Verdict.BREAKING
    if kinds & _SOURCE_BREAK_KINDS:
        return Verdict.SOURCE_BREAK
    # Only COMPATIBLE_KINDS changes (ELF warnings, deployment risks)
    if kinds - _COMPATIBLE_KINDS == set():
        return Verdict.COMPATIBLE
    # Unclassified change kinds default to BREAKING (fail-safe)
    return Verdict.BREAKING


def compare(
    old: AbiSnapshot,
    new: AbiSnapshot,
    suppression: SuppressionList | None = None,
) -> DiffResult:
    """Diff two AbiSnapshots and return a DiffResult with verdict."""

    changes: list[Change] = []
    changes.extend(_diff_functions(old, new))
    changes.extend(_diff_variables(old, new))
    changes.extend(_diff_types(old, new))
    changes.extend(_diff_enums(old, new))
    changes.extend(_diff_method_qualifiers(old, new))
    changes.extend(_diff_unions(old, new))
    changes.extend(_diff_typedefs(old, new))
    changes.extend(_diff_elf(old, new))
    changes.extend(_diff_dwarf(old, new))
    changes.extend(_diff_advanced_dwarf(old, new))
    # Sprint 7: full ABICC parity + beyond
    changes.extend(_diff_enum_renames(old, new))
    changes.extend(_diff_field_qualifiers(old, new))
    changes.extend(_diff_field_renames(old, new))
    changes.extend(_diff_param_defaults(old, new))
    changes.extend(_diff_param_renames(old, new))
    changes.extend(_diff_pointer_levels(old, new))
    changes.extend(_diff_access_levels(old, new))
    changes.extend(_diff_anon_fields(old, new))

    suppressed: list[Change] = []
    if suppression is not None:
        filtered: list[Change] = []
        for c in changes:
            if suppression.is_suppressed(c):
                suppressed.append(c)
            else:
                filtered.append(c)
        changes = filtered

    verdict = _compute_verdict(changes)
    return DiffResult(
        old_version=old.version,
        new_version=new.version,
        library=old.library,
        changes=changes,
        verdict=verdict,
        suppressed_count=len(suppressed),
        suppressed_changes=suppressed,
        suppression_file_provided=suppression is not None,
    )


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
            # - still includes explicit size drift when known on both sides
            type_name_changed = old_f.type_name != new_f.type_name
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

        # 2. Removed members
        for mname in sorted(old_e.members.keys() - new_e.members.keys()):
            changes.append(Change(
                kind=ChangeKind.ENUM_MEMBER_REMOVED,
                symbol=f"{name}::{mname}",
                description=f"Enum member removed: {name}::{mname}",
                old_value=str(old_e.members[mname]),
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
        "struct_packing_changed": ChangeKind.STRUCT_PACKING_CHANGED,
        "toolchain_flag_drift": ChangeKind.TOOLCHAIN_FLAG_DRIFT,
        "type_visibility_changed": ChangeKind.TYPE_VISIBILITY_CHANGED,
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
