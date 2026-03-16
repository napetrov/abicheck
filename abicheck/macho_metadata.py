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

"""Mach-O metadata for macOS/iOS dynamic libraries (.dylib / .framework).

Uses ``macholib`` for parsing Mach-O headers, load commands, exported symbols,
and dependency information from Apple shared libraries. Supports both
single-arch and fat/universal binaries (preferred arch slice is analyzed).
"""
from __future__ import annotations

import logging
import os
import platform
import stat
import struct
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Any

from macholib.mach_o import (  # type: ignore[import-untyped]
    CPU_TYPE_NAMES,
    LC_BUILD_VERSION,
    LC_ID_DYLIB,
    LC_LOAD_DYLIB,
    LC_REEXPORT_DYLIB,
    LC_VERSION_MIN_MACOSX,
    N_EXT,
    N_TYPE,
    N_UNDF,
    N_WEAK_DEF,
)
from macholib.MachO import MachO  # type: ignore[import-untyped]
from macholib.SymbolTable import SymbolTable  # type: ignore[import-untyped]

log = logging.getLogger(__name__)

# macholib uses lowercase short names ("dylib"); we use the traditional MH_* form.
_FILETYPE_NAMES: dict[int, str] = {
    1: "MH_OBJECT",
    2: "MH_EXECUTE",
    3: "MH_FVMLIB",
    4: "MH_CORE",
    5: "MH_PRELOAD",
    6: "MH_DYLIB",
    7: "MH_DYLINKER",
    8: "MH_BUNDLE",
    9: "MH_DYLIB_STUB",
    10: "MH_DSYM",
    11: "MH_KEXT_BUNDLE",
}


class MachoSymbolType(str, Enum):
    EXPORTED = "exported"     # N_EXT: externally visible
    WEAK = "weak"             # N_WEAK_DEF: weak definition
    REEXPORT = "reexport"     # re-exported from another dylib
    OTHER = "other"


@dataclass
class MachoExport:
    """A single exported symbol from a Mach-O binary."""
    name: str
    sym_type: MachoSymbolType = MachoSymbolType.EXPORTED
    is_weak: bool = False


@dataclass
class MachoMetadata:
    """Mach-O metadata from a macOS dynamic library.

    NOTE: Do NOT add ``frozen=True`` — ``@cached_property`` requires a
    writable ``__dict__``.
    """
    # Binary characteristics
    cpu_type: str = ""                   # e.g. "ARM64", "X86_64"
    filetype: str = ""                   # e.g. "MH_DYLIB", "MH_BUNDLE"
    flags: int = 0                       # MH_* flags bitmask

    # Install name (equivalent of ELF SONAME)
    install_name: str = ""               # LC_ID_DYLIB install name

    # Dependencies (equivalent of ELF DT_NEEDED)
    dependent_libs: list[str] = field(default_factory=list)  # LC_LOAD_DYLIB

    # Re-exported libraries
    reexported_libs: list[str] = field(default_factory=list)  # LC_REEXPORT_DYLIB

    # Exported symbols
    exports: list[MachoExport] = field(default_factory=list)

    # Version info from LC_ID_DYLIB
    current_version: str = ""            # e.g. "1.2.3"
    compat_version: str = ""             # e.g. "1.0.0"

    # Minimum OS version
    min_os_version: str = ""             # from LC_VERSION_MIN_MACOSX or LC_BUILD_VERSION

    @cached_property
    def export_map(self) -> dict[str, MachoExport]:
        """Name → MachoExport mapping (built once, cached on first access)."""
        return {e.name: e for e in self.exports if e.name}


# ---------------------------------------------------------------------------
# Magic detection
# ---------------------------------------------------------------------------

# Mach-O magic numbers (both byte orders + fat/universal binaries)
_MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",   # MH_MAGIC (32-bit)
    b"\xce\xfa\xed\xfe",   # MH_CIGAM (32-bit, swapped)
    b"\xfe\xed\xfa\xcf",   # MH_MAGIC_64 (64-bit)
    b"\xcf\xfa\xed\xfe",   # MH_CIGAM_64 (64-bit, swapped)
    b"\xca\xfe\xba\xbe",   # FAT_MAGIC (universal binary)
    b"\xbe\xba\xfe\xca",   # FAT_CIGAM (universal, swapped)
    b"\xca\xfe\xba\xbf",   # FAT_MAGIC_64 (fat64 universal binary)
    b"\xbf\xba\xfe\xca",   # FAT_CIGAM_64 (fat64, swapped)
}


def is_macho(path: Path) -> bool:
    """Check if file starts with a Mach-O magic number."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            return magic in _MACHO_MAGICS
    except OSError:
        return False


def _version_str(packed: int) -> str:
    """Convert packed Mach-O version (xxxx.yy.zz) to string."""
    major = (packed >> 16) & 0xFFFF
    minor = (packed >> 8) & 0xFF
    patch = packed & 0xFF
    return f"{major}.{minor}.{patch}"


def _dylib_name_from_cmd(data: bytes) -> str:
    """Extract the library name string from dylib load command data.

    In macholib's command tuple ``(lc, cmd, data)``, *data* contains the
    raw bytes that follow the typed command struct — for dylib commands
    this is exactly the null-terminated library path.
    """
    if not data:
        return ""
    end = data.find(b"\x00")
    if end < 0:
        end = len(data)
    return data[:end].decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_macho_metadata(dylib_path: Path) -> MachoMetadata:
    """Extract Mach-O export/import metadata from *dylib_path*.

    Uses ``macholib`` for parsing. For fat/universal binaries, selects the
    host-architecture slice (arm64 or x86_64); falls back to the first
    available slice.

    Returns an empty ``MachoMetadata`` on any parse error (logged as WARNING).
    """
    try:
        with open(dylib_path, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                log.warning("parse_macho_metadata: not a regular file: %s", dylib_path)
                return MachoMetadata()

        return _parse(dylib_path)
    except (OSError, ValueError, KeyError, struct.error) as exc:
        log.warning("parse_macho_metadata: failed to parse %s: %s", dylib_path, exc)
        return MachoMetadata()


def _select_header(macho: MachO) -> Any:
    """Pick the best architecture header from a (possibly fat) MachO object.

    Prefers arm64 on Apple Silicon, x86_64 otherwise; falls back to first.
    Returns a ``MachOHeader`` instance or *None*.
    """
    if not macho.headers:
        return None
    if len(macho.headers) == 1:
        return macho.headers[0]

    # CPU type constants
    _CPU_TYPE_X86_64 = 0x01000007  # pylint: disable=invalid-name
    _CPU_TYPE_ARM64 = 0x0100000C  # pylint: disable=invalid-name

    preferred = _CPU_TYPE_ARM64 if platform.machine() in ("arm64", "aarch64") else _CPU_TYPE_X86_64
    fallback_type = _CPU_TYPE_X86_64 if preferred == _CPU_TYPE_ARM64 else _CPU_TYPE_ARM64

    for hdr in macho.headers:
        if int(hdr.header.cputype) == preferred:
            return hdr
    for hdr in macho.headers:
        if int(hdr.header.cputype) == fallback_type:
            return hdr
    return macho.headers[0]


def _parse(dylib_path: Path) -> MachoMetadata:
    """Parse Mach-O metadata using macholib."""
    macho = MachO(str(dylib_path))
    header = _select_header(macho)
    if header is None:
        return MachoMetadata()

    meta = MachoMetadata()
    hdr = header.header

    # Basic header info
    cputype = int(hdr.cputype)
    meta.cpu_type = CPU_TYPE_NAMES.get(cputype, f"0x{cputype:x}")
    filetype = int(hdr.filetype)
    meta.filetype = _FILETYPE_NAMES.get(filetype, f"0x{filetype:x}")
    meta.flags = int(hdr.flags)

    # Parse load commands
    for lc, cmd, data in header.commands:
        cmd_type = lc.cmd

        if cmd_type == LC_ID_DYLIB:
            meta.install_name = _dylib_name_from_cmd(data)
            meta.current_version = str(cmd.current_version)
            meta.compat_version = str(cmd.compatibility_version)

        elif cmd_type == LC_LOAD_DYLIB:
            name = _dylib_name_from_cmd(data)
            if name:
                meta.dependent_libs.append(name)

        elif cmd_type == LC_REEXPORT_DYLIB:
            name = _dylib_name_from_cmd(data)
            if name:
                meta.reexported_libs.append(name)

        elif cmd_type == LC_VERSION_MIN_MACOSX:
            meta.min_os_version = _version_str(int(cmd.version))  # p_uint32

        elif cmd_type == LC_BUILD_VERSION:
            meta.min_os_version = _version_str(int(cmd.minos))  # p_uint32

    # Parse exported symbols via SymbolTable
    try:
        symtab = SymbolTable(macho, header=header)
        # Prefer extdefsyms (available when LC_DYSYMTAB is present),
        # fall back to nlists (all symbols) with manual N_EXT filtering.
        symbols = getattr(symtab, "extdefsyms", None) or symtab.nlists
        for nlist_entry, name_bytes in symbols:
            n_type = int(nlist_entry.n_type)
            n_desc = int(nlist_entry.n_desc)

            # Only exported, defined symbols
            if not (n_type & N_EXT):
                continue
            if (n_type & N_TYPE) == N_UNDF:
                continue

            name = name_bytes.decode("utf-8", errors="replace") if name_bytes else ""
            # Strip leading underscore (Mach-O C symbol convention)
            if name.startswith("_"):
                name = name[1:]

            is_weak = bool(n_desc & N_WEAK_DEF)
            sym_type = MachoSymbolType.WEAK if is_weak else MachoSymbolType.EXPORTED
            meta.exports.append(MachoExport(name=name, sym_type=sym_type, is_weak=is_weak))
    except Exception as exc:  # noqa: BLE001
        # SymbolTable may fail on binaries without LC_SYMTAB (stripped, .tbd stubs, etc.)
        log.debug("parse_macho_metadata: SymbolTable failed for %s: %s", dylib_path, exc)

    return meta
