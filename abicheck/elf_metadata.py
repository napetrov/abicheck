"""ELF dynamic-section and symbol-table metadata.

Uses ``pyelftools`` (pure Python, actively maintained) for robust ELF/DWARF
parsing instead of text-scraping ``readelf`` output.

See ADR-001 for technology stack rationale.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from pathlib import Path

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
    WEAK   = "weak"
    LOCAL  = "local"
    OTHER  = "other"


class SymbolType(str, Enum):
    FUNC   = "func"
    OBJECT = "object"
    TLS    = "tls"
    IFUNC  = "ifunc"   # STT_GNU_IFUNC
    COMMON = "common"  # STT_COMMON
    NOTYPE = "notype"
    OTHER  = "other"


@dataclass
class ElfSymbol:
    name: str
    binding:  SymbolBinding = SymbolBinding.GLOBAL
    sym_type: SymbolType    = SymbolType.FUNC
    size:     int           = 0
    version:  str           = ""    # e.g. "GLIBC_2.5" or "" if unversioned
    is_default: bool        = True  # @@ (default) vs @ (non-default)
    visibility: str         = "default"  # default / hidden / protected / internal


@dataclass
class ElfMetadata:
    """ELF dynamic-section + symbol metadata for one .so."""
    soname:  str = ""
    needed:  list[str] = field(default_factory=list)
    rpath:   str = ""
    runpath: str = ""

    # Symbol versions defined by this library (.gnu.version_d)
    versions_defined: list[str] = field(default_factory=list)
    # Symbol versions required from other libraries (.gnu.version_r)
    # dict: library_soname → list of version strings
    versions_required: dict[str, list[str]] = field(default_factory=dict)

    # Exported symbols (.dynsym, GLOBAL/WEAK, not UND, not hidden)
    symbols: list[ElfSymbol] = field(default_factory=list)

    @cached_property
    def symbol_map(self) -> dict[str, ElfSymbol]:
        """Name → ElfSymbol mapping (cached, built once)."""
        return {s.name: s for s in self.symbols}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_BINDING_MAP: dict[str, SymbolBinding] = {
    "STB_GLOBAL": SymbolBinding.GLOBAL,
    "STB_WEAK":   SymbolBinding.WEAK,
    "STB_LOCAL":  SymbolBinding.LOCAL,
}

_TYPE_MAP: dict[str, SymbolType] = {
    "STT_FUNC":      SymbolType.FUNC,
    "STT_OBJECT":    SymbolType.OBJECT,
    "STT_TLS":       SymbolType.TLS,
    "STT_GNU_IFUNC": SymbolType.IFUNC,
    "STT_COMMON":    SymbolType.COMMON,
    "STT_NOTYPE":    SymbolType.NOTYPE,
}

_HIDDEN_VISIBILITIES = {"STV_HIDDEN", "STV_INTERNAL"}


def parse_elf_metadata(so_path: Path) -> ElfMetadata:
    """Extract ELF dynamic + symbol metadata from *so_path* using pyelftools."""
    # Validate input: must be a regular file (not symlink, pipe, etc.)
    resolved = so_path.resolve()
    if not resolved.is_file():
        log.warning("parse_elf_metadata: not a regular file: %s", so_path)
        return ElfMetadata()

    try:
        with open(resolved, "rb") as f:
            return _parse(f)
    except (ELFError, OSError) as exc:
        log.warning("parse_elf_metadata: failed to parse %s: %s", so_path, exc)
        return ElfMetadata()


def _parse(f: object) -> ElfMetadata:  # type: ignore[name-defined]
    meta = ElfMetadata()
    elf = ELFFile(f)

    for section in elf.iter_sections():
        if isinstance(section, DynamicSection):
            _parse_dynamic(section, meta)
        elif isinstance(section, GNUVerDefSection):
            _parse_version_def(section, meta)
        elif isinstance(section, GNUVerNeedSection):
            _parse_version_need(section, meta)
        elif isinstance(section, SymbolTableSection) and section.name == ".dynsym":
            _parse_dynsym(section, meta)

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
    for verdef, verdaux_iter in section.iter_versions():
        for verdaux in verdaux_iter:
            name = verdaux.name
            if name and name not in meta.versions_defined:
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
        # Skip undefined symbols
        if sym.entry.st_shndx == "SHN_UNDEF":
            continue

        binding_str  = sym.entry.st_info.bind
        type_str     = sym.entry.st_info.type
        vis_str      = sym.entry.st_other.visibility

        binding = _BINDING_MAP.get(binding_str, SymbolBinding.OTHER)

        # Skip local symbols — not part of public ABI surface
        if binding == SymbolBinding.LOCAL:
            continue

        # Skip hidden/internal symbols — not exported from DSO
        if vis_str in _HIDDEN_VISIBILITIES:
            continue

        sym_type = _TYPE_MAP.get(type_str, SymbolType.OTHER)
        name     = sym.name

        # Strip version suffix if present (e.g. "foo@@GLIBC_2.5" → name="foo", version="GLIBC_2.5")
        version    = ""
        is_default = True
        if "@@" in name:
            name, version = name.split("@@", 1)
            is_default = True
        elif "@" in name:
            name, version = name.split("@", 1)
            is_default = False

        meta.symbols.append(ElfSymbol(
            name=name,
            binding=binding,
            sym_type=sym_type,
            size=sym.entry.st_size,
            version=version,
            is_default=is_default,
            visibility=vis_str.replace("STV_", "").lower(),
        ))
