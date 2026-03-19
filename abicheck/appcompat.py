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

"""Application compatibility checking — ADR-005.

Answers: "Will my application still work with the new library version?"
by intersecting the app's required symbols with the library diff.

See docs/adr/005-application-compat-check.md for the full design.
"""
from __future__ import annotations

import logging
import os
import stat
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .checker import Change, DiffResult, compare
from .checker_policy import ChangeKind, Verdict, compute_verdict

if TYPE_CHECKING:
    from .policy_file import PolicyFile
    from .suppression import SuppressionList

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AppRequirements:
    """Symbols and versions an application binary requires from a library."""

    needed_libs: list[str] = field(default_factory=list)
    undefined_symbols: set[str] = field(default_factory=set)
    required_versions: dict[str, str] = field(default_factory=dict)


@dataclass
class AppCompatResult:
    """Result of checking app compatibility with a library update."""

    app_path: str
    old_lib_path: str
    new_lib_path: str

    # App's requirements
    required_symbols: set[str] = field(default_factory=set)
    required_symbol_count: int = 0

    # Filtered results
    breaking_for_app: list[Change] = field(default_factory=list)
    irrelevant_for_app: list[Change] = field(default_factory=list)
    missing_symbols: list[str] = field(default_factory=list)
    missing_versions: list[str] = field(default_factory=list)

    # Full library diff (for reference)
    full_diff: DiffResult | None = None

    # App-specific verdict
    verdict: Verdict = Verdict.COMPATIBLE

    # Coverage
    symbol_coverage: float = 100.0  # % of app's required symbols present in new lib


# ---------------------------------------------------------------------------
# Binary format detection
# ---------------------------------------------------------------------------


def _detect_app_format(app_path: Path) -> str | None:
    """Detect binary format of an application: 'elf', 'pe', or 'macho'.

    Delegates to the shared detector with an extra S_ISREG check for
    application paths (which may be symlinks or pipes).
    """
    try:
        with open(app_path, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                return None
    except OSError:
        return None
    from .binary_utils import detect_binary_format
    return detect_binary_format(app_path)


# ---------------------------------------------------------------------------
# ELF: parse app requirements
# ---------------------------------------------------------------------------

def _parse_elf_app_requirements(
    app_path: Path, library_soname: str,
) -> AppRequirements:
    """Extract app requirements for a specific library from an ELF binary.

    Reads .dynsym for UNDEF symbols, correlates with .gnu.version and
    .gnu.version_r to filter symbols to those imported from ``library_soname``.
    """
    from elftools.common.exceptions import ELFError
    from elftools.elf.dynamic import DynamicSection
    from elftools.elf.elffile import ELFFile
    from elftools.elf.gnuversions import GNUVerNeedSection, GNUVerSymSection
    from elftools.elf.sections import SymbolTableSection

    reqs = AppRequirements()

    try:
        with open(app_path, "rb") as f:
            elf = ELFFile(f)

            # 1. Read DT_NEEDED entries
            for section in elf.iter_sections():
                if isinstance(section, DynamicSection):
                    for tag in section.iter_tags():
                        if tag.entry.d_tag == "DT_NEEDED":
                            reqs.needed_libs.append(tag.needed)

            # 2. Build version-index → library SONAME map from .gnu.version_r
            #    Each vernaux entry has vna_other (the version index used in
            #    .gnu.version) and the parent verneed names the source library.
            ver_idx_to_lib: dict[int, str] = {}
            for section in elf.iter_sections():
                if isinstance(section, GNUVerNeedSection):
                    for verneed, vernaux_iter in section.iter_versions():
                        lib = verneed.name
                        for vernaux in vernaux_iter:
                            ver_idx = vernaux.entry.vna_other
                            ver_idx_to_lib[ver_idx] = lib
                            ver = vernaux.name
                            # Collect required version tags for the target library
                            if ver and library_soname and lib == library_soname:
                                reqs.required_versions[ver] = lib

            # 3. Read .gnu.version section (per-symbol version indices)
            versym_section: GNUVerSymSection | None = None
            for section in elf.iter_sections():
                if isinstance(section, GNUVerSymSection):
                    versym_section = section
                    break

            # 4. Read undefined symbols from .dynsym, filtered by target library
            for section in elf.iter_sections():
                if isinstance(section, SymbolTableSection) and section.name == ".dynsym":
                    for idx, sym in enumerate(section.iter_symbols()):
                        if sym.entry.st_shndx != "SHN_UNDEF":
                            continue
                        if not sym.name:
                            continue
                        binding = sym.entry.st_info.bind
                        if binding not in ("STB_GLOBAL", "STB_WEAK"):
                            continue

                        # Filter by source library using .gnu.version correlation
                        if library_soname and versym_section is not None:
                            try:
                                ver_entry = versym_section.get_symbol(idx)
                                ver_ndx = ver_entry.entry["ndx"]
                                # pyelftools returns str for special indices
                                # (VER_NDX_LOCAL, VER_NDX_GLOBAL) and int for
                                # regular version indices.
                                if isinstance(ver_ndx, str):
                                    ver_ndx = 0 if ver_ndx == "VER_NDX_LOCAL" else 1
                                else:
                                    # Mask off the hidden bit (bit 15)
                                    ver_ndx = ver_ndx & 0x7FFF
                            except (IndexError, KeyError):
                                ver_ndx = 1  # treat as unversioned

                            if ver_ndx >= 2:
                                # Versioned symbol — check if from target library
                                source_lib = ver_idx_to_lib.get(ver_ndx, "")
                                if source_lib != library_soname:
                                    continue
                            elif ver_ndx <= 1:
                                # Unversioned symbol (index 0=local, 1=global).
                                # Cannot determine source library from version info;
                                # include only if it doesn't look like a system symbol.
                                from .elf_metadata import _guess_symbol_origin
                                origin = _guess_symbol_origin(
                                    sym.name, reqs.needed_libs,
                                )
                                if origin is not None:
                                    continue
                                # Weak undefined symbols with unknown origin are
                                # typically optional linker/runtime refs (e.g.
                                # _ITM_*, __gmon_start__) — skip them.
                                if binding == "STB_WEAK":
                                    continue

                        reqs.undefined_symbols.add(sym.name)

    except (ELFError, OSError, ValueError) as exc:
        log.warning("Failed to parse ELF app requirements from %s: %s", app_path, exc)

    return reqs


# ---------------------------------------------------------------------------
# PE: parse app requirements
# ---------------------------------------------------------------------------

def _parse_pe_app_requirements(
    app_path: Path, library_name: str,
) -> AppRequirements:
    """Extract app requirements for a specific DLL from a PE binary."""
    import pefile

    reqs = AppRequirements()
    library_name_lower = library_name.lower() if library_name else ""

    try:
        pe = pefile.PE(str(app_path), fast_load=True)
        try:
            pe.parse_data_directories(
                directories=[
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                ]
            )

            if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
                for entry in pe.DIRECTORY_ENTRY_IMPORT:
                    dll_name = entry.dll.decode("utf-8", errors="replace") if entry.dll else ""
                    reqs.needed_libs.append(dll_name)

                    # Only collect symbols for the target DLL
                    if library_name_lower and dll_name.lower() != library_name_lower:
                        continue

                    for imp in entry.imports:
                        if imp.name:
                            reqs.undefined_symbols.add(
                                imp.name.decode("utf-8", errors="replace")
                            )
                        elif getattr(imp, "import_by_ordinal", False):
                            reqs.undefined_symbols.add(f"ordinal:{imp.ordinal}")
        finally:
            pe.close()

    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to parse PE app requirements from %s: %s", app_path, exc)

    return reqs


# ---------------------------------------------------------------------------
# Mach-O: parse app requirements
# ---------------------------------------------------------------------------

def _parse_macho_app_requirements(
    app_path: Path, library_name: str,
) -> AppRequirements:
    """Extract app requirements for a specific dylib from a Mach-O binary."""
    from macholib.mach_o import (
        LC_LOAD_DYLIB,
        N_EXT,
        N_TYPE,
        N_UNDF,
    )
    from macholib.MachO import MachO
    from macholib.SymbolTable import SymbolTable

    reqs = AppRequirements()

    try:
        macho = MachO(str(app_path))
        if not macho.headers:
            return reqs

        header = macho.headers[0]

        # 1. Read dependent libraries
        for lc, cmd, data in header.commands:
            if lc.cmd == LC_LOAD_DYLIB:
                if data:
                    end = data.find(b"\x00")
                    if end < 0:
                        end = len(data)
                    name = data[:end].decode("utf-8", errors="replace")
                    reqs.needed_libs.append(name)

        # 2. Determine index of target library in LC_LOAD_DYLIB list (1-based)
        #    In Mach-O two-level namespace, the library ordinal stored in
        #    n_desc bits [15:8] is a 1-based index into the load-dylib list.
        target_ordinal: int | None = None
        if library_name:
            lib_lower = library_name.lower()
            for idx, lib in enumerate(reqs.needed_libs, start=1):
                # Match by exact path, basename, or install_name
                if (lib.lower() == lib_lower
                        or os.path.basename(lib).lower() == lib_lower
                        or lib_lower in lib.lower()):
                    target_ordinal = idx
                    break

        # 3. Read undefined symbols, filtered by target library ordinal
        try:
            symtab = SymbolTable(macho, header=header)
            # Check undefsyms first (available when LC_DYSYMTAB is present)
            symbols = getattr(symtab, "undefsyms", None) or symtab.nlists
            for nlist_entry, name_bytes in symbols:
                n_type = int(nlist_entry.n_type)

                # For undefsyms, they're already filtered. For nlists, filter manually.
                if symbols is symtab.nlists:
                    if not (n_type & N_EXT):
                        continue
                    if (n_type & N_TYPE) != N_UNDF:
                        continue

                # Filter by library ordinal when target is known
                if target_ordinal is not None:
                    n_desc = int(nlist_entry.n_desc)
                    ordinal = (n_desc >> 8) & 0xFF
                    # 0 = SELF, 0xFE = EXECUTABLE, 0xFF = DYNAMIC_LOOKUP
                    if ordinal not in (0, 0xFE, 0xFF) and ordinal != target_ordinal:
                        continue

                name = name_bytes.decode("utf-8", errors="replace") if name_bytes else ""
                # Strip leading underscore (Mach-O C symbol convention)
                if name.startswith("_"):
                    name = name[1:]
                if name:
                    reqs.undefined_symbols.add(name)
        except Exception as exc:  # noqa: BLE001
            log.debug("SymbolTable failed for %s: %s", app_path, exc)

    except (OSError, ValueError, struct.error) as exc:
        log.warning("Failed to parse Mach-O app requirements from %s: %s", app_path, exc)

    return reqs


# ---------------------------------------------------------------------------
# Public API: parse_app_requirements
# ---------------------------------------------------------------------------

def parse_app_requirements(
    app_path: Path, library_name: str,
) -> AppRequirements:
    """Extract app's requirements for a specific library.

    Args:
        app_path: Path to the application binary (ELF, PE, or Mach-O).
        library_name: SONAME/DLL name/dylib path to filter by.

    Returns:
        AppRequirements with the app's needed libs, undefined symbols,
        and required versions.

    Raises:
        ValueError: If the binary format cannot be detected.
    """
    fmt = _detect_app_format(app_path)
    if fmt == "elf":
        return _parse_elf_app_requirements(app_path, library_name)
    if fmt == "pe":
        return _parse_pe_app_requirements(app_path, library_name)
    if fmt == "macho":
        return _parse_macho_app_requirements(app_path, library_name)
    raise ValueError(
        f"Cannot detect binary format of '{app_path}'. "
        "Expected: ELF, PE, or Mach-O executable."
    )


# ---------------------------------------------------------------------------
# Filtering: is a change relevant to the app?
# ---------------------------------------------------------------------------

def _is_relevant_to_app(change: Change, app: AppRequirements) -> bool:
    """Does this change affect a symbol the application uses?

    FIX-A Part 3: handles two symbol format mismatches:
    1. change.symbol may be C++-mangled while app uses plain C names
    2. change.affected_symbols now includes both mangled and demangled names
    """
    # Direct symbol match
    if change.symbol in app.undefined_symbols:
        return True

    # Demangled fallback for change.symbol (FIX-A Part 3, Mismatch 1):
    # change.symbol may be C++-mangled (e.g. "_Z3addii") while app uses
    # the plain C linker name (e.g. "add").
    from .demangle import demangle as _demangle_symbol
    plain = _demangle_symbol(change.symbol)
    if plain and plain != change.symbol and plain in app.undefined_symbols:
        return True

    # Type change affecting app's symbols (via affected_symbols enrichment).
    # affected_symbols now contains both demangled and mangled names (FIX-A Part 3).
    if change.affected_symbols:
        if app.undefined_symbols & set(change.affected_symbols):
            return True

    # ELF-level: SONAME change affects all consumers
    if change.kind == ChangeKind.SONAME_CHANGED:
        return True

    # Mach-O compat version change affects all consumers
    if change.kind == ChangeKind.COMPAT_VERSION_CHANGED:
        return True

    # Symbol version removal for a version the app requires.
    # change.symbol is the version tag (e.g. "FOO_1.0"); app.required_versions
    # maps version_tag → library_soname.  If the tag is in the map, the app
    # depends on it and the removal is relevant.
    if change.kind == ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED:
        if change.symbol in app.required_versions:
            return True

    return False


# ---------------------------------------------------------------------------
# Get new library exported symbols
# ---------------------------------------------------------------------------

def _get_new_lib_exports(new_lib_path: Path) -> set[str]:
    """Get the set of exported symbol names from the new library."""
    fmt = _detect_app_format(new_lib_path)
    if fmt == "elf":
        from .elf_metadata import parse_elf_metadata
        elf_meta = parse_elf_metadata(new_lib_path)
        return {s.name for s in elf_meta.symbols}
    if fmt == "pe":
        from .pe_metadata import parse_pe_metadata
        pe_meta = parse_pe_metadata(new_lib_path)
        return {e.name for e in pe_meta.exports if e.name}
    if fmt == "macho":
        from .macho_metadata import parse_macho_metadata
        macho_meta = parse_macho_metadata(new_lib_path)
        return {e.name for e in macho_meta.exports if e.name}
    return set()


def _get_lib_soname(lib_path: Path) -> str:
    """Get the SONAME/install_name/DLL name from a library."""
    fmt = _detect_app_format(lib_path)
    if fmt == "elf":
        from .elf_metadata import parse_elf_metadata
        elf_meta = parse_elf_metadata(lib_path)
        return elf_meta.soname or lib_path.name
    if fmt == "pe":
        return lib_path.name
    if fmt == "macho":
        from .macho_metadata import parse_macho_metadata
        macho_meta = parse_macho_metadata(lib_path)
        return macho_meta.install_name or lib_path.name
    return lib_path.name


# ---------------------------------------------------------------------------
# Core: appcompat check
# ---------------------------------------------------------------------------

def check_appcompat(
    app_path: Path,
    old_lib_path: Path,
    new_lib_path: Path,
    *,
    headers: list[Path] | None = None,
    includes: list[Path] | None = None,
    old_headers: list[Path] | None = None,
    new_headers: list[Path] | None = None,
    old_includes: list[Path] | None = None,
    new_includes: list[Path] | None = None,
    old_version: str = "old",
    new_version: str = "new",
    lang: str = "c++",
    suppression: SuppressionList | None = None,
    policy: str = "strict_abi",
    policy_file: PolicyFile | None = None,
) -> AppCompatResult:
    """Check application compatibility with a library update.

    1. Parse app binary → extract required symbols
    2. Run standard compare() on libraries
    3. Check symbol availability in new library
    4. Filter changes by app usage
    5. Compute app-specific verdict
    """
    # Get library SONAME for filtering
    library_soname = _get_lib_soname(old_lib_path)

    # 1. Parse app requirements
    app_reqs = parse_app_requirements(app_path, library_soname)

    # 2. Run standard library comparison
    from .dumper import dump

    # Resolve per-side headers: old_headers/new_headers override shared headers
    _old_h = old_headers if old_headers is not None else (headers or [])
    _new_h = new_headers if new_headers is not None else (headers or [])
    _old_inc = old_includes if old_includes is not None else (includes or [])
    _new_inc = new_includes if new_includes is not None else (includes or [])

    old_snap = dump(
        so_path=old_lib_path,
        headers=_old_h,
        extra_includes=_old_inc,
        version=old_version,
        compiler="c++" if lang == "c++" else "cc",
        lang="c" if lang == "c" else None,
    )
    new_snap = dump(
        so_path=new_lib_path,
        headers=_new_h,
        extra_includes=_new_inc,
        version=new_version,
        compiler="c++" if lang == "c++" else "cc",
        lang="c" if lang == "c" else None,
    )

    diff = compare(old_snap, new_snap, suppression=suppression, policy=policy, policy_file=policy_file)

    # 3. Check symbol availability in new library
    new_exports = _get_new_lib_exports(new_lib_path)
    missing_symbols = sorted(
        sym for sym in app_reqs.undefined_symbols
        if sym not in new_exports
    )

    # Check version availability
    missing_versions: list[str] = []
    if _detect_app_format(new_lib_path) == "elf":
        from .elf_metadata import parse_elf_metadata
        new_elf_meta = parse_elf_metadata(new_lib_path)
        new_defined_versions = set(new_elf_meta.versions_defined)
        for ver_tag, _lib in app_reqs.required_versions.items():
            if ver_tag not in new_defined_versions:
                missing_versions.append(ver_tag)

    # 4. Filter diff by app usage
    breaking_for_app: list[Change] = []
    irrelevant_for_app: list[Change] = []
    for change in diff.changes:
        if _is_relevant_to_app(change, app_reqs):
            breaking_for_app.append(change)
        else:
            irrelevant_for_app.append(change)

    # 5. Compute app-specific verdict
    required_count = len(app_reqs.undefined_symbols)
    if new_exports:
        coverage = (
            (required_count - len(missing_symbols)) / required_count * 100.0
            if required_count > 0 else 100.0
        )
    else:
        coverage = 0.0 if required_count > 0 else 100.0

    # Verdict: missing symbols/versions → BREAKING, else based on relevant changes
    if missing_symbols or missing_versions:
        verdict = Verdict.BREAKING
    elif breaking_for_app:
        verdict = (
            policy_file.compute_verdict(breaking_for_app)
            if policy_file is not None
            else compute_verdict(breaking_for_app, policy=policy)
        )
    else:
        verdict = Verdict.COMPATIBLE if required_count > 0 else Verdict.NO_CHANGE

    return AppCompatResult(
        app_path=str(app_path),
        old_lib_path=str(old_lib_path),
        new_lib_path=str(new_lib_path),
        required_symbols=app_reqs.undefined_symbols,
        required_symbol_count=required_count,
        breaking_for_app=breaking_for_app,
        irrelevant_for_app=irrelevant_for_app,
        missing_symbols=missing_symbols,
        missing_versions=missing_versions,
        full_diff=diff,
        verdict=verdict,
        symbol_coverage=coverage,
    )


# ---------------------------------------------------------------------------
# Weak mode: check-against (no old library needed)
# ---------------------------------------------------------------------------

def check_against(
    app_path: Path,
    new_lib_path: Path,
) -> AppCompatResult:
    """Check if a library provides everything the app needs (weak mode).

    No old library required — just checks symbol availability.
    """
    library_name = _get_lib_soname(new_lib_path)
    app_reqs = parse_app_requirements(app_path, library_name)

    new_exports = _get_new_lib_exports(new_lib_path)
    missing_symbols = sorted(
        sym for sym in app_reqs.undefined_symbols
        if sym not in new_exports
    )

    # Check version availability for ELF
    missing_versions: list[str] = []
    if _detect_app_format(new_lib_path) == "elf":
        from .elf_metadata import parse_elf_metadata
        new_elf_meta = parse_elf_metadata(new_lib_path)
        new_defined_versions = set(new_elf_meta.versions_defined)
        for ver_tag, _lib in app_reqs.required_versions.items():
            if ver_tag not in new_defined_versions:
                missing_versions.append(ver_tag)

    required_count = len(app_reqs.undefined_symbols)
    if new_exports:
        coverage = (
            (required_count - len(missing_symbols)) / required_count * 100.0
            if required_count > 0 else 100.0
        )
    else:
        coverage = 0.0 if required_count > 0 else 100.0

    verdict = Verdict.BREAKING if (missing_symbols or missing_versions) else Verdict.COMPATIBLE

    return AppCompatResult(
        app_path=str(app_path),
        old_lib_path="",
        new_lib_path=str(new_lib_path),
        required_symbols=app_reqs.undefined_symbols,
        required_symbol_count=required_count,
        breaking_for_app=[],
        irrelevant_for_app=[],
        missing_symbols=missing_symbols,
        missing_versions=missing_versions,
        full_diff=None,
        verdict=verdict,
        symbol_coverage=coverage,
    )
