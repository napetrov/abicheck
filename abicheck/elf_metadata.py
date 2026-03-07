"""ELF dynamic-section and symbol-table metadata.

Extracted via ``readelf`` — no debug info required.  Covers:
- DT_SONAME, DT_NEEDED, DT_RPATH, DT_RUNPATH
- .gnu.version_d / .gnu.version_r  (defined / required symbol versions)
- Per-symbol: binding, type, visibility, size  (from .dynsym)
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


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
    binding: SymbolBinding = SymbolBinding.GLOBAL
    sym_type: SymbolType   = SymbolType.FUNC
    size: int              = 0
    version: str           = ""   # e.g. "GLIBC_2.5" or "" if unversioned
    is_default: bool       = True  # @@ vs @ (default vs non-default version)


@dataclass
class ElfMetadata:
    """ELF dynamic-section + symbol metadata for one .so."""
    soname:   str = ""
    needed:   list[str] = field(default_factory=list)   # DT_NEEDED entries
    rpath:    str = ""   # DT_RPATH value (or "")
    runpath:  str = ""   # DT_RUNPATH value (or "")

    # Symbol versions defined by this library (.gnu.version_d)
    versions_defined: list[str] = field(default_factory=list)
    # Symbol versions required from other libraries (.gnu.version_r)
    # dict: library_soname -> set of version strings
    versions_required: dict[str, list[str]] = field(default_factory=dict)

    # Exported symbols (.dynsym, GLOBAL/WEAK, not UND)
    symbols: list[ElfSymbol] = field(default_factory=list)

    @property
    def symbol_map(self) -> dict[str, ElfSymbol]:
        return {s.name: s for s in self.symbols}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


def parse_elf_metadata(so_path: Path) -> ElfMetadata:
    """Extract ELF dynamic + symbol metadata from *so_path* using readelf."""
    meta = ElfMetadata()
    _parse_dynamic(so_path, meta)
    _parse_version_sections(so_path, meta)
    _parse_dynsym(so_path, meta)
    return meta


def _parse_dynamic(so_path: Path, meta: ElfMetadata) -> None:
    out = _run(["readelf", "-d", str(so_path)])
    for line in out.splitlines():
        line = line.strip()
        if "(SONAME)" in line:
            m = re.search(r'Library soname: \[(.+?)\]', line)
            if m:
                meta.soname = m.group(1)
        elif "(NEEDED)" in line:
            m = re.search(r'Shared library: \[(.+?)\]', line)
            if m:
                meta.needed.append(m.group(1))
        elif "(RPATH)" in line:
            m = re.search(r'Library rpath: \[(.+?)\]', line)
            if m:
                meta.rpath = m.group(1)
        elif "(RUNPATH)" in line:
            m = re.search(r'Library runpath: \[(.+?)\]', line)
            if m:
                meta.runpath = m.group(1)


def _parse_version_sections(so_path: Path, meta: ElfMetadata) -> None:
    # -V: version definitions + requirements
    out = _run(["readelf", "-V", str(so_path)])
    section = ""
    cur_lib = ""
    for line in out.splitlines():
        low = line.strip().lower()
        if "version definition" in low:
            section = "def"
        elif "version needs" in low:
            section = "req"

        if section == "def":
            # Lines like:  0x0001  0x0001  2  libfoo_1.0
            m = re.search(r'\b([A-Za-z_][A-Za-z0-9_.]*)\s*$', line.strip())
            if m and not line.strip().startswith("0x"):
                ver = m.group(1)
                if ver not in ("section", "version", "definition",
                               "definitions", "needs", "symbols"):
                    meta.versions_defined.append(ver)
        elif section == "req":
            # "  Filename: libstdc++.so.6 (2 needed)"
            m_lib = re.search(r'Filename:\s+(\S+)', line)
            if m_lib:
                cur_lib = m_lib.group(1)
                if cur_lib not in meta.versions_required:
                    meta.versions_required[cur_lib] = []
            # "  0x0d696911  0x00  02  GLIBCXX_3.4"
            m_ver = re.search(r'\b([A-Z][A-Z0-9_.]+_[\d.]+)\b', line)
            if m_ver and cur_lib:
                ver = m_ver.group(1)
                if ver not in meta.versions_required[cur_lib]:
                    meta.versions_required[cur_lib].append(ver)


def _parse_dynsym(so_path: Path, meta: ElfMetadata) -> None:
    out = _run(["readelf", "-s", "--dyn-syms", str(so_path)])
    _binding_map = {
        "global": SymbolBinding.GLOBAL,
        "weak":   SymbolBinding.WEAK,
        "local":  SymbolBinding.LOCAL,
    }
    _type_map = {
        "func":   SymbolType.FUNC,
        "object": SymbolType.OBJECT,
        "tls":    SymbolType.TLS,
        "gnu_ifunc": SymbolType.IFUNC,
        "common": SymbolType.COMMON,
        "notype": SymbolType.NOTYPE,
    }
    for line in out.splitlines():
        # readelf -s line format (GNU):
        # Num:    Value          Size Type    Bind   Vis      Ndx Name
        #   1: 0000000000000000     0 FUNC    GLOBAL DEFAULT  UND __libc_start_main@@GLIBC_2.34
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            int(parts[0].rstrip(":"))
        except ValueError:
            continue
        size_str, sym_type_str, binding_str, _, ndx, raw_name = (
            parts[2], parts[3], parts[4], parts[5], parts[6], parts[7]
        )
        # Skip undefined / local symbols
        if ndx == "UND":
            continue
        binding = _binding_map.get(binding_str.lower(), SymbolBinding.OTHER)
        if binding == SymbolBinding.LOCAL:
            continue
        sym_type = _type_map.get(sym_type_str.lower(), SymbolType.OTHER)
        # Parse versioned name:  foo@@VER_1  or  foo@VER_1  or  foo
        version = ""
        is_default = True
        name = raw_name
        if "@@" in raw_name:
            name, version = raw_name.split("@@", 1)
            is_default = True
        elif "@" in raw_name:
            name, version = raw_name.split("@", 1)
            is_default = False
        try:
            size = int(size_str)
        except ValueError:
            size = 0
        meta.symbols.append(ElfSymbol(
            name=name, binding=binding, sym_type=sym_type,
            size=size, version=version, is_default=is_default,
        ))
