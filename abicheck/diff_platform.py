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

"Platform-specific ABI diff detectors (ELF, PE, Mach-O, DWARF)."
from __future__ import annotations

import re
from typing import Any

from .checker_policy import ChangeKind
from .checker_types import Change
from .diff_symbols import _PUBLIC_VIS, _public_functions
from .diff_types import _RESERVED_FIELD_RE
from .dwarf_advanced import diff_advanced_dwarf
from .elf_metadata import SymbolBinding, SymbolType
from .model import (
    AbiSnapshot,
    Function,
    Visibility,
)

# Module-level constant: ELF visibility values that form the default<->protected pair (case51).
_ELF_VIS_PROTECTED_PAIR: frozenset[str] = frozenset({"default", "protected"})

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
    if o.install_name != n.install_name and (o.install_name or n.install_name):
        changes.append(Change(
            kind=ChangeKind.SONAME_CHANGED,
            symbol="LC_ID_DYLIB",
            old_value=o.install_name,
            new_value=n.install_name,
            description=f"install name changed: {o.install_name} → {n.install_name}",
        ))

    # Compatibility version change (LC_ID_DYLIB compat_version — binary contract)
    if o.compat_version != n.compat_version and (o.compat_version or n.compat_version):
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

    # PT_GNU_STACK executable stack detection (security bad practice)
    old_exec = getattr(old_elf, "has_executable_stack", False)
    new_exec = getattr(new_elf, "has_executable_stack", False)
    if old_exec != new_exec:
        changes.append(Change(
            kind=ChangeKind.EXECUTABLE_STACK,
            symbol="PT_GNU_STACK",
            description=(
                "Executable stack detected: library linked with -Wl,-z,execstack — NX protection disabled (security risk)"
                if new_exec
                else "Executable stack removed: library now uses non-executable stack (good practice)"
            ),
            old_value="RWE" if old_exec else "RW",
            new_value="RWE" if new_exec else "RW",
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

    # ELF st_other visibility transition (DEFAULT↔PROTECTED↔HIDDEN↔INTERNAL)
    if s_old.visibility != s_new.visibility:
        old_vis = s_old.visibility
        new_vis = s_new.visibility
        # HIDDEN/INTERNAL transitions are already caught by FUNC_VISIBILITY_CHANGED
        # or FUNC_REMOVED (symbol disappears from exported set). Only emit for
        # transitions among exported visibilities (DEFAULT↔PROTECTED).
        if old_vis not in ("hidden", "internal") and new_vis not in ("hidden", "internal"):
            changes.append(Change(
                kind=ChangeKind.SYMBOL_ELF_VISIBILITY_CHANGED,
                symbol=sym_name,
                description=f"ELF visibility changed: {sym_name} ({old_vis} → {new_vis})",
                old_value=old_vis,
                new_value=new_vis,
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

    # case51: ELF visibility default→protected (or vice-versa) — function symbols only.
    # Data symbols with default→protected break copy relocations (real ABI break).
    # Only for functions is this safely compatible (interposition semantics change only).
    old_vis = getattr(s_old, "visibility", "default") or "default"
    new_vis = getattr(s_new, "visibility", "default") or "default"
    if (
        old_vis != new_vis
        and {old_vis, new_vis} == _ELF_VIS_PROTECTED_PAIR
        and getattr(s_old, "sym_type", None) == SymbolType.FUNC
    ):
        changes.append(Change(
            kind=ChangeKind.FUNC_VISIBILITY_PROTECTED_CHANGED,
            symbol=sym_name,
            description=(
                f"ELF symbol visibility changed: {sym_name} "
                f"({old_vis} → {new_vis}); symbol still exported, "
                f"interposition semantics changed"
            ),
            old_value=old_vis,
            new_value=new_vis,
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

    # Collect opaque (forward-declared only) struct names from each side.
    # If a struct is opaque in *both* snapshots, its layout is not part of
    # the public ABI — callers never see the fields — so DWARF layout
    # changes should be suppressed.
    old_opaque = {t.name for t in old.types if getattr(t, "is_opaque", False)}
    new_opaque = {t.name for t in new.types if getattr(t, "is_opaque", False)}
    both_opaque = old_opaque & new_opaque

    allowed_structs: set[str] = (
        {t.name for t in old.types} | {t.name for t in new.types}
    ) - both_opaque
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
    from .dwarf_metadata import FieldInfo, StructLayout

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

        # 3. Removed fields — check for reserved-field activations first
        removed_names = sorted(old_fields.keys() - new_fields.keys())
        added_names = new_fields.keys() - old_fields.keys()
        # Build added-field index by byte_offset for reserved-field matching
        added_by_offset: dict[int, FieldInfo] = {
            new_fields[fn].byte_offset: new_fields[fn]
            for fn in added_names
            if not _RESERVED_FIELD_RE.match(fn)
        }
        reserved_matched: set[str] = set()

        for fname in removed_names:
            if _RESERVED_FIELD_RE.match(fname):
                old_f = old_fields[fname]
                candidate = added_by_offset.get(old_f.byte_offset)
                if candidate is not None and not _RESERVED_FIELD_RE.match(candidate.name):
                    changes.append(Change(
                        kind=ChangeKind.USED_RESERVED_FIELD,
                        symbol=name,
                        description=f"Reserved field put into use: {name}::{fname} → {candidate.name}",
                        old_value=fname,
                        new_value=candidate.name,
                    ))
                    reserved_matched.add(candidate.name)
                    continue
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
        # Sentinel detection: name-pattern based (*_last, *_max, *_count).
        # More robust than max-value heuristics for evolving enums.
        _SENTINEL_SUFFIXES = ("_last", "_max", "_count")

        def _is_sentinel_member(member_name: str) -> bool:
            n = member_name.lower()
            return n.endswith(_SENTINEL_SUFFIXES) or n in {"last", "max", "count"}

        for mname, old_val in old_e.members.items():
            if mname in new_e.members and new_e.members[mname] != old_val:
                kind = (
                    ChangeKind.ENUM_LAST_MEMBER_VALUE_CHANGED
                    if _is_sentinel_member(mname)
                    else ChangeKind.ENUM_MEMBER_VALUE_CHANGED
                )
                changes.append(Change(
                    kind=kind,
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

        # NOTE: We intentionally do NOT skip inline transitions here.
        # When a function becomes inline AND its symbol vanishes from .dynsym,
        # this is a binary break for pre-compiled consumers. The
        # FUNC_BECAME_INLINE detector (API_BREAK) fires separately for the
        # source-level concern; this detector adds FUNC_DELETED_ELF_FALLBACK
        # (BREAKING) for the binary-level concern.

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

