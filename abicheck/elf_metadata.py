"""ELF dynamic-section and symbol-table metadata.

Uses ``pyelftools`` (pure Python, actively maintained) for robust ELF/DWARF
parsing instead of text-scraping ``readelf`` output.

See docs/adr/001-technology-stack.md for rationale.
"""
from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import IO

from elftools.common.exceptions import ELFError
from elftools.elf.dynamic import DynamicSection
from elftools.elf.elffile import ELFFile
from elftools.elf.gnuversions import (
    GNUVerDefSection,
    GNUVerNeedSection,
)
from elftools.elf.sections import SymbolTableSection

log = logging.getLogger(__name__)


class SymbolBinding(str, Enum):
    GLOBAL = "global"
    WEAK = "weak"
    LOCAL = "local"
    OTHER = "other"


class SymbolType(str, Enum):
    FUNC = "func"
    OBJECT = "object"
    TLS = "tls"
    IFUNC = "ifunc"   # STT_GNU_IFUNC
    COMMON = "common"  # STT_COMMON
    NOTYPE = "notype"
    OTHER = "other"


@dataclass
class ElfSymbol:
    name: str
    binding: SymbolBinding = SymbolBinding.GLOBAL
    sym_type: SymbolType = SymbolType.FUNC
    size: int = 0
    version: str = ""       # version tag from .gnu.version_d/.gnu.version_r
    is_default: bool = True
    visibility: str = "default"  # default / hidden / protected / internal


@dataclass
class ElfMetadata:
    """ELF dynamic-section + symbol metadata for one .so.

    NOTE: Do NOT add ``frozen=True`` to this dataclass — ``@cached_property``
    (used by ``symbol_map``) requires a writable instance ``__dict__``.
    """
    soname: str = ""
    needed: list[str] = field(default_factory=list)
    rpath: str = ""
    runpath: str = ""

    # Symbol versions defined by this library (.gnu.version_d)
    versions_defined: list[str] = field(default_factory=list)
    # Symbol versions required from other libraries (.gnu.version_r)
    # dict: library_soname → list of version strings
    versions_required: dict[str, list[str]] = field(default_factory=dict)

    # Exported symbols (.dynsym, GLOBAL/WEAK, not UND, not hidden/internal)
    symbols: list[ElfSymbol] = field(default_factory=list)

    @cached_property
    def symbol_map(self) -> dict[str, ElfSymbol]:
        """Name → ElfSymbol mapping (built once, cached on first access).

        Thread safety: benign race — both threads compute the same dict;
        the last write wins. Functionally correct for read-only use.
        """
        return {s.name: s for s in self.symbols}


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_BINDING_MAP: dict[str, SymbolBinding] = {
    "STB_GLOBAL": SymbolBinding.GLOBAL,
    "STB_WEAK": SymbolBinding.WEAK,
    "STB_LOCAL": SymbolBinding.LOCAL,
}

_TYPE_MAP: dict[str, SymbolType] = {
    "STT_FUNC": SymbolType.FUNC,
    "STT_OBJECT": SymbolType.OBJECT,
    "STT_TLS": SymbolType.TLS,
    "STT_GNU_IFUNC": SymbolType.IFUNC,
    # pyelftools < 0.33 reports STT_GNU_IFUNC (type=10, OS-specific range) as STT_LOOS.
    # On Linux ELF, STT_LOOS == STT_GNU_IFUNC, so we map it to IFUNC.
    "STT_LOOS": SymbolType.IFUNC,
    "STT_COMMON": SymbolType.COMMON,
    "STT_NOTYPE": SymbolType.NOTYPE,
}

_HIDDEN_VISIBILITIES = frozenset({"STV_HIDDEN", "STV_INTERNAL"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_elf_metadata(so_path: Path) -> ElfMetadata:
    """Extract ELF dynamic + symbol metadata from *so_path* using pyelftools.

    Returns an empty ``ElfMetadata`` on any parse error (logged as WARNING).
    Uses fstat() after open() to prevent TOCTOU symlink/FIFO attacks.
    """
    try:
        with open(so_path, "rb") as f:
            # Verify it's a regular file *after* open to avoid TOCTOU race.
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                log.warning("parse_elf_metadata: not a regular file: %s", so_path)
                return ElfMetadata()
            return _parse(f, so_path)
    except (ELFError, OSError, ValueError) as exc:
        log.warning("parse_elf_metadata: failed to open/parse %s: %s", so_path, exc)
        return ElfMetadata()


# ---------------------------------------------------------------------------
# Internal parsing
# ---------------------------------------------------------------------------

def _parse(f: IO[bytes], so_path: Path) -> ElfMetadata:
    meta = ElfMetadata()
    elf = ELFFile(f)

    for section in elf.iter_sections():
        try:
            if isinstance(section, DynamicSection):
                _parse_dynamic(section, meta)
            elif isinstance(section, GNUVerDefSection):
                _parse_version_def(section, meta)
            elif isinstance(section, GNUVerNeedSection):
                _parse_version_need(section, meta)
            elif isinstance(section, SymbolTableSection) and section.name == ".dynsym":
                _parse_dynsym(section, meta)
        except Exception as exc:  # noqa: BLE001
            # Partial-success: log malformed section, keep results from other sections.
            log.warning("parse_elf_metadata: skipping malformed section %r in %s: %s",
                        section.name, so_path, exc)

    # Post-loop: filter out version-definition auxiliary symbols.
    # These appear in .dynsym as OBJECT/size=0 entries (e.g. LIBFOO_1.0) but
    # are ELF artefacts of --version-script, not real exported functions.
    _ver_def_names: set[str] = set(meta.versions_defined)
    if _ver_def_names:
        meta.symbols = [
            sym for sym in meta.symbols
            if not (
                sym.name in _ver_def_names
                and sym.size == 0
                and sym.sym_type == SymbolType.OBJECT
            )
        ]

    return meta


def _parse_dynamic(section: DynamicSection, meta: ElfMetadata) -> None:
    for tag in section.iter_tags():
        if tag.entry.d_tag == "DT_SONAME":
            meta.soname = tag.soname
        elif tag.entry.d_tag == "DT_NEEDED":
            meta.needed.append(tag.needed)
        elif tag.entry.d_tag == "DT_RPATH":
            meta.rpath = tag.rpath
        elif tag.entry.d_tag == "DT_RUNPATH":
            meta.runpath = tag.runpath


def _parse_version_def(section: GNUVerDefSection, meta: ElfMetadata) -> None:
    # ELF version definition section (.gnu.version_d).
    # The first entry has VER_FLG_BASE (flags==1) and names the SONAME -- skip it.
    # Only real named version nodes (e.g. LIBFOO_1.0) should appear in versions_defined.
    VER_FLG_BASE = 0x1
    for verdef, verdaux_iter in section.iter_versions():
        is_base = bool(verdef.entry.vd_flags & VER_FLG_BASE)
        for verdaux in verdaux_iter:
            name = verdaux.name
            if name and not is_base and name not in meta.versions_defined:
                meta.versions_defined.append(name)


def _parse_version_need(section: GNUVerNeedSection, meta: ElfMetadata) -> None:
    for verneed, vernaux_iter in section.iter_versions():
        lib = verneed.name
        if lib not in meta.versions_required:
            meta.versions_required[lib] = []
        for vernaux in vernaux_iter:
            ver = vernaux.name
            if ver and ver not in meta.versions_required[lib]:
                meta.versions_required[lib].append(ver)


def _parse_dynsym(section: SymbolTableSection, meta: ElfMetadata) -> None:
    for sym in section.iter_symbols():
        # Skip undefined symbols (imported, not exported)
        if sym.entry.st_shndx == "SHN_UNDEF":
            continue

        binding_str = sym.entry.st_info.bind
        type_str = sym.entry.st_info.type
        vis_str = sym.entry.st_other.visibility

        binding = _BINDING_MAP.get(binding_str, SymbolBinding.OTHER)

        # Skip local symbols — not part of public ABI surface
        if binding == SymbolBinding.LOCAL:
            continue

        # Skip hidden/internal — not exported from DSO
        if vis_str in _HIDDEN_VISIBILITIES:
            continue

        sym_type = _TYPE_MAP.get(type_str, SymbolType.OTHER)
        name = sym.name

        # NOTE: pyelftools does NOT embed version suffixes (@@/@ notation) in
        # sym.name — that's a readelf text-output artifact. Symbol version info
        # comes from the .gnu.version section correlated with .gnu.version_d/r,
        # which is parsed separately in _parse_version_def/_parse_version_need.
        # We leave version="" here; callers correlate via versions_defined/required.

        meta.symbols.append(ElfSymbol(
            name=name,
            binding=binding,
            sym_type=sym_type,
            size=sym.entry.st_size,
            version="",
            is_default=True,
            visibility=vis_str.replace("STV_", "").lower(),
        ))
