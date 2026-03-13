"""Central change policy registry and verdict computation."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ChangeKind(str, Enum):
    # Function / variable changes
    FUNC_REMOVED = "func_removed"        # public symbol removed → BREAKING
    FUNC_REMOVED_ELF_ONLY = "func_removed_elf_only"  # ELF-only symbol removed (visibility cleanup, not hard break)
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
    SONAME_MISSING = "soname_missing"             # old library had no SONAME — bad practice
    VISIBILITY_LEAK = "visibility_leak"            # library exports internal symbols without -fvisibility=hidden
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
    SYMBOL_VERSION_DEFINED_ADDED = "symbol_version_defined_added"   # versioning introduced
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
    VALUE_ABI_TRAIT_CHANGED = "value_abi_trait_changed"         # DWARF triviality-based calling conv heuristic
    STRUCT_PACKING_CHANGED = "struct_packing_changed"       # __attribute__((packed)) added/removed
    TYPE_VISIBILITY_CHANGED = "type_visibility_changed"      # typeinfo/vtable visibility changed
    TOOLCHAIN_FLAG_DRIFT = "toolchain_flag_drift"         # -fshort-enums/-fpack-struct drift
    FRAME_REGISTER_CHANGED = "frame_register_changed"      # CFA/frame-pointer convention changed (#117)

    # Sprint 2 — gap detectors
    FUNC_DELETED = "func_deleted"                        # = delete added → BREAKING (was callable)
    VAR_BECAME_CONST = "var_became_const"                # non-const → const: writes → SIGSEGV
    VAR_LOST_CONST = "var_lost_const"                    # const → non-const: BREAKING (ODR / inlining)
    TYPE_BECAME_OPAQUE = "type_became_opaque"            # complete → forward-decl only → BREAKING
    BASE_CLASS_POSITION_CHANGED = "base_class_position_changed"  # base reorder → this-ptr offset change
    BASE_CLASS_VIRTUAL_CHANGED = "base_class_virtual_changed"    # base became virtual or non-virtual

    # ── Sprint 7 — Full ABICC parity + beyond ────────────────────────────
    # Source-level breaks (not binary ABI, but API contract)
    ENUM_MEMBER_RENAMED = "enum_member_renamed"              # same value, different name → API_BREAK
    PARAM_DEFAULT_VALUE_CHANGED = "param_default_value_changed"  # default arg changed
    PARAM_DEFAULT_VALUE_REMOVED = "param_default_value_removed"  # default arg removed → API_BREAK
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

    # ── ABICC full parity — remaining gaps ─────────────────────────────────
    # Global data value
    VAR_VALUE_CHANGED = "var_value_changed"                  # global data initial value changed

    # Aggregate kind change
    TYPE_KIND_CHANGED = "type_kind_changed"                  # union-involving transition (struct→union, union→struct, class→union, union→class)
    SOURCE_LEVEL_KIND_CHANGED = "source_level_kind_changed"  # struct↔class transition (non-breaking, source-only)

    # Reserved field
    USED_RESERVED_FIELD = "used_reserved_field"              # __reserved field put into use

    # Const overload removal
    REMOVED_CONST_OVERLOAD = "removed_const_overload"        # const method overload removed

    # Parameter restrict qualifier
    PARAM_RESTRICT_CHANGED = "param_restrict_changed"        # restrict qualifier added/removed

    # Parameter va_list
    PARAM_BECAME_VA_LIST = "param_became_va_list"            # fixed param → va_list
    PARAM_LOST_VA_LIST = "param_lost_va_list"                # va_list → fixed param

    # Preprocessor constants
    CONSTANT_CHANGED = "constant_changed"                    # #define value changed
    CONSTANT_ADDED = "constant_added"                        # new #define
    CONSTANT_REMOVED = "constant_removed"                    # #define removed

    # Global data access level
    VAR_ACCESS_CHANGED = "var_access_changed"                # public→private/protected variable (narrowing)
    VAR_ACCESS_WIDENED = "var_access_widened"                 # private/protected→public variable (widening)

    # ── Inline attribute changes (ABICC issue #125) ─────────────────────────────
    FUNC_BECAME_INLINE = "func_became_inline"   # function became inline — symbol may disappear from DSO
    FUNC_LOST_INLINE = "func_lost_inline"        # function lost inline — now has external linkage (compatible)

    # ── PR #89: ELF fallback for = delete (issue #100) ───────────────────────────
    # Emitted when castxml metadata lacks deleted="1" but the symbol disappears
    # from the ELF .dynsym while the header model still declares the function.
    # This is a best-effort fallback; lower confidence than FUNC_DELETED.
    FUNC_DELETED_ELF_FALLBACK = "func_deleted_elf_fallback"

    # ── PR #89: Template inner-type deep analysis (issues #38 / #73) ─────────────
    # Emitted when a function param or return type is a template specialization
    # whose inner type argument(s) change, e.g. vector<int> → vector<double>.
    TEMPLATE_PARAM_TYPE_CHANGED = "template_param_type_changed"
    TEMPLATE_RETURN_TYPE_CHANGED = "template_return_type_changed"


class HasKind(Protocol):
    kind: ChangeKind


class Verdict(str, Enum):
    NO_CHANGE = "NO_CHANGE"         # identical ABI
    COMPATIBLE = "COMPATIBLE"       # only additions
    API_BREAK = "API_BREAK"   # source-level break, binary compatible
    BREAKING = "BREAKING"           # binary ABI break


# Which ChangeKinds are immediately BREAKING (binary ABI incompatibility)
BREAKING_KINDS = {
    ChangeKind.FUNC_REMOVED,
    # ELF-only function removed in no-header mode is treated as
    # potential visibility cleanup, not hard ABI break.
    # (see checker._diff_functions + AbiSnapshot.elf_only_mode provenance)
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
    # NOTE: SYMBOL_VERSION_REQUIRED_ADDED moved to COMPATIBLE_KINDS (see below)
    # DWARF Sprint 3 + 4
    ChangeKind.STRUCT_SIZE_CHANGED,
    ChangeKind.STRUCT_FIELD_OFFSET_CHANGED,
    ChangeKind.STRUCT_FIELD_REMOVED,
    ChangeKind.STRUCT_FIELD_TYPE_CHANGED,
    ChangeKind.STRUCT_ALIGNMENT_CHANGED,
    ChangeKind.ENUM_UNDERLYING_SIZE_CHANGED,
    ChangeKind.CALLING_CONVENTION_CHANGED,
    ChangeKind.VALUE_ABI_TRAIT_CHANGED,
    ChangeKind.STRUCT_PACKING_CHANGED,
    ChangeKind.FRAME_REGISTER_CHANGED,        # CFA/frame-pointer convention changed (#117)
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
    # ABICC full parity
    ChangeKind.TYPE_KIND_CHANGED,            # struct→union: layout completely changes
    # PR #89: ELF fallback for = delete (binary break — symbol disappeared from DSO)
    # PR #89: Template inner-type changes are binary ABI breaks (different instantiation layout)
    ChangeKind.TEMPLATE_PARAM_TYPE_CHANGED,
    ChangeKind.TEMPLATE_RETURN_TYPE_CHANGED,
    ChangeKind.FUNC_DELETED_ELF_FALLBACK,  # ELF heuristic — symbol absent from dynsym is binary-incompatible
}

COMPATIBLE_KINDS: set[ChangeKind] = {
    # Header/API additions
    ChangeKind.FUNC_ADDED,
    ChangeKind.VAR_ADDED,
    ChangeKind.TYPE_ADDED,
    # TYPE_FIELD_ADDED intentionally omitted: compatible only for standard-layout
    # non-polymorphic types; context-aware verdict set in _diff_types()
    ChangeKind.TYPE_FIELD_ADDED_COMPATIBLE,
    # ELF-only removed: symbol was never declared in headers, may be visibility cleanup
    ChangeKind.FUNC_REMOVED_ELF_ONLY,
    # ELF quality improvements
    ChangeKind.SONAME_MISSING,
    ChangeKind.VISIBILITY_LEAK,
    ChangeKind.SYMBOL_VERSION_DEFINED_ADDED,

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
    # New symbol version requirement: existing binaries are unaffected (already linked);
    # this is a deployment risk (requires target OS ≥ that glibc version) but NOT a
    # binary ABI break for already-compiled consumers. Produced false positives on
    # real-world patch releases (libpng 1.6.43→1.6.44, zlib 1.3.0→1.3.1) where
    # GLIBC_2.14 (released 2011) was flagged as BREAKING.
    ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED,

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

    # ABICC full parity — informational/compatible changes
    ChangeKind.PARAM_RESTRICT_CHANGED,       # restrict is an optimization hint, not ABI-breaking
    ChangeKind.PARAM_BECAME_VA_LIST,         # va_list transition: informational
    ChangeKind.PARAM_LOST_VA_LIST,           # va_list transition: informational
    ChangeKind.CONSTANT_ADDED,               # new constant: compatible addition
    ChangeKind.USED_RESERVED_FIELD,          # reserved field put into use: compatible (was unused)
    ChangeKind.VAR_VALUE_CHANGED,            # global data value change: compatible (compile-time risk only)
    ChangeKind.VAR_ACCESS_WIDENED,           # private/protected→public: widening is compatible

    # Inline attribute changes
    ChangeKind.FUNC_LOST_INLINE,             # losing inline gives the function external linkage — existing
                                             # binaries with baked-in inline copies still work correctly
}

API_BREAK_KINDS: set[ChangeKind] = {
    # Source-level breaks: code won't compile but existing binaries are fine
    ChangeKind.ENUM_MEMBER_RENAMED,
    ChangeKind.PARAM_DEFAULT_VALUE_REMOVED,
    ChangeKind.FIELD_RENAMED,
    ChangeKind.PARAM_RENAMED,
    ChangeKind.METHOD_ACCESS_CHANGED,
    ChangeKind.FIELD_ACCESS_CHANGED,
    # ABICC full parity — source breaks
    ChangeKind.REMOVED_CONST_OVERLOAD,       # const overload removed: source code calling const version breaks
    ChangeKind.CONSTANT_CHANGED,             # #define value changed: source-level semantic change
    ChangeKind.CONSTANT_REMOVED,             # #define removed: source code referencing it breaks
    ChangeKind.VAR_ACCESS_CHANGED,           # variable access narrowed: source-level break
    ChangeKind.SOURCE_LEVEL_KIND_CHANGED,    # struct↔class: source-level keyword change, binary identical

    # Inline attribute changes (potentially breaking: symbol may vanish from DSO)
    ChangeKind.FUNC_BECAME_INLINE,           # function became inline — callers compiled against old header
                                             # may get UNDEFINED when linking against new DSO if the symbol
                                             # is now emitted only inline; needs manual review
}

# ---------------------------------------------------------------------------
# Policy-specific downgrade sets
# ---------------------------------------------------------------------------

# sdk_vendor: source-level-only kinds that are in API_BREAK_KINDS but do not
# affect already-compiled binary consumers. Under sdk_vendor policy they are
# downgraded from API_BREAK → COMPATIBLE (no warning emitted).
# All members MUST be in API_BREAK_KINDS — enforced by the assertion below.
SDK_VENDOR_COMPAT_KINDS: frozenset[ChangeKind] = frozenset({
    ChangeKind.ENUM_MEMBER_RENAMED,
    ChangeKind.FIELD_RENAMED,
    ChangeKind.PARAM_RENAMED,
    ChangeKind.METHOD_ACCESS_CHANGED,
    ChangeKind.FIELD_ACCESS_CHANGED,
    ChangeKind.SOURCE_LEVEL_KIND_CHANGED,   # struct↔class: binary-identical
    ChangeKind.REMOVED_CONST_OVERLOAD,
    ChangeKind.PARAM_DEFAULT_VALUE_REMOVED,
    # NOTE: PARAM_DEFAULT_VALUE_CHANGED is intentionally omitted — it already
    # lives in COMPATIBLE_KINDS, so including it here would be a no-op.
})

# Deprecated alias kept for external consumers; will be removed in v2.0.
SDK_VENDOR_DOWNGRADED_KINDS: frozenset[ChangeKind] = SDK_VENDOR_COMPAT_KINDS

# plugin_abi: kinds that are acceptable when the plugin and host are built from
# the same toolchain at the same time (single-process boundary).
# These are all in BREAKING_KINDS and are downgraded from BREAKING → COMPATIBLE.
# All members MUST be in BREAKING_KINDS — enforced by the assertion below.
PLUGIN_ABI_DOWNGRADED_KINDS: frozenset[ChangeKind] = frozenset({
    # NOTE: TOOLCHAIN_FLAG_DRIFT is intentionally omitted — it already lives in
    # COMPATIBLE_KINDS (informational), so it is not in BREAKING_KINDS and
    # including it here would be a silent no-op in the subtraction logic.
    ChangeKind.CALLING_CONVENTION_CHANGED,
    ChangeKind.FRAME_REGISTER_CHANGED,      # CFA register = physical calling convention
    # VALUE_ABI_TRAIT_CHANGED: DWARF trivially-copyable heuristic controls
    # pass-by-register vs pass-by-pointer in the Itanium C++ ABI. Under
    # plugin_abi this is safe to downgrade ONLY because the plugin and host
    # are always rebuilt together from the same toolchain — ensuring ABI
    # triviality decisions are in sync. Do NOT include this in sdk_vendor.
    ChangeKind.VALUE_ABI_TRAIT_CHANGED,
})

# Integrity assertions: catch miscategorisation at import time.
assert SDK_VENDOR_COMPAT_KINDS <= API_BREAK_KINDS, (
    "SDK_VENDOR_COMPAT_KINDS must be a strict subset of API_BREAK_KINDS; "
    f"offending kinds: {SDK_VENDOR_COMPAT_KINDS - API_BREAK_KINDS}"
)
assert PLUGIN_ABI_DOWNGRADED_KINDS <= BREAKING_KINDS, (
    "PLUGIN_ABI_DOWNGRADED_KINDS must be a strict subset of BREAKING_KINDS; "
    f"offending kinds: {PLUGIN_ABI_DOWNGRADED_KINDS - BREAKING_KINDS}"
)


@dataclass(frozen=True)
class PolicyEntry:
    default_verdict: Verdict
    severity: str
    doc_slug: str


POLICY_REGISTRY: dict[ChangeKind, PolicyEntry] = {
    k: PolicyEntry(Verdict.BREAKING, "error", k.value) for k in BREAKING_KINDS
} | {
    k: PolicyEntry(Verdict.API_BREAK, "warning", k.value) for k in API_BREAK_KINDS
} | {
    k: PolicyEntry(Verdict.COMPATIBLE, "warning", k.value) for k in COMPATIBLE_KINDS
}


def policy_for(kind: ChangeKind) -> PolicyEntry:
    """Get policy metadata for a ChangeKind.

    Unknown kinds are treated as BREAKING by default (fail-safe).
    """
    return POLICY_REGISTRY.get(kind, PolicyEntry(Verdict.BREAKING, "error", kind.value))


def policy_registry_markdown() -> str:
    """Build a markdown snippet for docs from the policy registry."""
    lines = [
        "| ChangeKind | Default verdict | Severity | Doc slug |",
        "|---|---|---|---|",
    ]
    for kind in sorted(ChangeKind, key=lambda k: k.value):
        entry = policy_for(kind)
        lines.append(
            f"| `{kind.value}` | `{entry.default_verdict.value}` | "
            f"`{entry.severity}` | `{entry.doc_slug}` |"
        )
    return "\n".join(lines)

VALID_BASE_POLICIES: frozenset[str] = frozenset({"strict_abi", "sdk_vendor", "plugin_abi"})
"""Canonical set of valid built-in policy names. Import from here — do not redefine."""


def policy_kind_sets(policy: str) -> tuple[frozenset[ChangeKind], frozenset[ChangeKind], frozenset[ChangeKind]]:
    """Return (breaking, api_break, compatible) kind sets for the given policy name.

    This is the single source of truth for policy → kind-set mapping.
    Used by compute_verdict(), DiffResult properties, and report classification.
    Unknown policy names fall back to strict_abi.
    """
    if policy == "sdk_vendor":
        return (
            frozenset(BREAKING_KINDS),
            frozenset(API_BREAK_KINDS - SDK_VENDOR_COMPAT_KINDS),
            frozenset(COMPATIBLE_KINDS | SDK_VENDOR_COMPAT_KINDS),
        )
    elif policy == "plugin_abi":
        return (
            frozenset(BREAKING_KINDS - PLUGIN_ABI_DOWNGRADED_KINDS),
            frozenset(API_BREAK_KINDS),
            frozenset(COMPATIBLE_KINDS | PLUGIN_ABI_DOWNGRADED_KINDS),
        )
    else:
        return frozenset(BREAKING_KINDS), frozenset(API_BREAK_KINDS), frozenset(COMPATIBLE_KINDS)


def compute_verdict(changes: Sequence[HasKind], *, policy: str = "strict_abi") -> Verdict:
    """Compute verdict from a list of changes, honoring the given policy profile.

    Policy profiles:
    - ``strict_abi`` (default): full BREAKING / API_BREAK sets apply.
    - ``sdk_vendor``: source-level-only kinds (rename, access) downgraded
      from API_BREAK → COMPATIBLE (no warning for SDK consumers).
    - ``plugin_abi``: calling-convention kinds (CALLING_CONVENTION_CHANGED,
      FRAME_REGISTER_CHANGED, VALUE_ABI_TRAIT_CHANGED) downgraded from
      BREAKING → COMPATIBLE. Only valid when plugin and host are always
      rebuilt together from the same toolchain.

    Unknown policy names fall back to ``strict_abi``.
    """
    if not changes:
        return Verdict.NO_CHANGE

    breaking, api_break, compatible = policy_kind_sets(policy)
    kinds = {c.kind for c in changes}
    if kinds & breaking:
        return Verdict.BREAKING
    if kinds & api_break:
        return Verdict.API_BREAK
    if kinds - compatible == set():
        return Verdict.COMPATIBLE
    # Unclassified change kinds default to BREAKING (fail-safe)
    return Verdict.BREAKING


# ---------------------------------------------------------------------------
# Deprecated aliases — kept for external consumers; will be removed in v2.0
# ---------------------------------------------------------------------------
#: Deprecated: use :data:`Verdict.API_BREAK`
SOURCE_BREAK: Verdict = Verdict.API_BREAK  # deprecated alias

#: Deprecated: use :data:`API_BREAK_KINDS`
SOURCE_BREAK_KINDS = API_BREAK_KINDS  # noqa: E305
