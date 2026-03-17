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

_ELF_MAGIC = b"\x7fELF"
_MZ_MAGIC = b"MZ"
_MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def _detect_app_format(app_path: Path) -> str | None:
    """Detect binary format of an application: 'elf', 'pe', or 'macho'."""
    try:
        with open(app_path, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                return None
            magic = f.read(4)
            if magic == _ELF_MAGIC:
                return "elf"
            if magic[:2] == _MZ_MAGIC:
                return "pe"
            if magic in _MACHO_MAGICS:
                return "macho"
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# ELF: parse app requirements
# ---------------------------------------------------------------------------

def _parse_elf_app_requirements(
    app_path: Path, library_soname: str,
) -> AppRequirements:
    """Extract app requirements for a specific library from an ELF binary.

    Reads .dynsym for UNDEF symbols and .gnu.version_r for required versions.
    """
    from elftools.common.exceptions import ELFError
    from elftools.elf.dynamic import DynamicSection
    from elftools.elf.elffile import ELFFile
    from elftools.elf.gnuversions import GNUVerNeedSection
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

            # 2. Read undefined symbols from .dynsym
            for section in elf.iter_sections():
                if isinstance(section, SymbolTableSection) and section.name == ".dynsym":
                    for sym in section.iter_symbols():
                        if sym.entry.st_shndx != "SHN_UNDEF":
                            continue
                        if not sym.name:
                            continue
                        binding = sym.entry.st_info.bind
                        if binding not in ("STB_GLOBAL", "STB_WEAK"):
                            continue
                        reqs.undefined_symbols.add(sym.name)

            # 3. Read required versions from .gnu.version_r
            for section in elf.iter_sections():
                if isinstance(section, GNUVerNeedSection):
                    for verneed, vernaux_iter in section.iter_versions():
                        lib = verneed.name
                        # Only collect versions for the target library
                        if library_soname and lib != library_soname:
                            continue
                        for vernaux in vernaux_iter:
                            ver = vernaux.name
                            if ver:
                                # Map: we don't have per-symbol version mapping
                                # from .gnu.version_r alone (that requires correlating
                                # .gnu.version with .dynsym indices). Store lib-level versions.
                                reqs.required_versions[ver] = lib

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
    import pefile  # type: ignore[import-untyped]

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
    from macholib.mach_o import (  # type: ignore[import-untyped]
        LC_LOAD_DYLIB,
        N_EXT,
        N_TYPE,
        N_UNDF,
    )
    from macholib.MachO import MachO  # type: ignore[import-untyped]
    from macholib.SymbolTable import SymbolTable  # type: ignore[import-untyped]

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

        # 2. Read undefined symbols
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
    """Does this change affect a symbol the application uses?"""
    # Direct symbol match
    if change.symbol in app.undefined_symbols:
        return True

    # Type change affecting app's symbols (via affected_symbols enrichment)
    if change.affected_symbols:
        if app.undefined_symbols & set(change.affected_symbols):
            return True

    # ELF-level: SONAME change affects all consumers
    if change.kind == ChangeKind.SONAME_CHANGED:
        return True

    # Mach-O compat version change affects all consumers
    if change.kind == ChangeKind.COMPAT_VERSION_CHANGED:
        return True

    # Symbol version change for a version the app requires
    if change.kind == ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED:
        sym = change.symbol
        required_ver = app.required_versions.get(sym)
        if required_ver and change.old_value and required_ver == change.old_value:
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
        meta = parse_elf_metadata(new_lib_path)
        return {s.name for s in meta.symbols}
    if fmt == "pe":
        from .pe_metadata import parse_pe_metadata
        meta = parse_pe_metadata(new_lib_path)
        return {e.name for e in meta.exports if e.name}
    if fmt == "macho":
        from .macho_metadata import parse_macho_metadata
        meta = parse_macho_metadata(new_lib_path)
        return {e.name for e in meta.exports if e.name}
    return set()


def _get_lib_soname(lib_path: Path) -> str:
    """Get the SONAME/install_name/DLL name from a library."""
    fmt = _detect_app_format(lib_path)
    if fmt == "elf":
        from .elf_metadata import parse_elf_metadata
        meta = parse_elf_metadata(lib_path)
        return meta.soname or lib_path.name
    if fmt == "pe":
        return lib_path.name
    if fmt == "macho":
        from .macho_metadata import parse_macho_metadata
        meta = parse_macho_metadata(lib_path)
        return meta.install_name or lib_path.name
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
    from .errors import AbicheckError

    old_snap = dump(
        so_path=old_lib_path,
        headers=headers or [],
        extra_includes=includes or [],
        version=old_version,
        compiler="c++" if lang == "c++" else "cc",
        lang="c" if lang == "c" else None,
    )
    new_snap = dump(
        so_path=new_lib_path,
        headers=headers or [],
        extra_includes=includes or [],
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

    # Verdict: missing symbols → BREAKING, else based on relevant changes
    if missing_symbols:
        verdict = Verdict.BREAKING
    elif breaking_for_app:
        verdict = compute_verdict(breaking_for_app, policy=policy)
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

    verdict = Verdict.BREAKING if missing_symbols else Verdict.COMPATIBLE

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
