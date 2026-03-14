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

Pure-Python parser for Mach-O headers, load commands, exported symbols,
and dependency information from Apple shared libraries. Supports both
single-arch and fat/universal binaries (first slice is analyzed).
"""
from __future__ import annotations

import logging
import os
import stat
import struct
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


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
}


def is_macho(path: Path) -> bool:
    """Check if file starts with a Mach-O magic number."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            return magic in _MACHO_MAGICS
    except OSError:
        return False


# ---------------------------------------------------------------------------
# CPU type mapping
# ---------------------------------------------------------------------------

_CPU_TYPE_NAMES: dict[int, str] = {
    1: "VAX",
    6: "MC680x0",
    7: "X86",
    0x01000007: "X86_64",
    12: "ARM",
    0x0100000C: "ARM64",
    14: "SPARC",
    18: "POWERPC",
    0x01000012: "POWERPC64",
}

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

# Mach-O load command constants
_LC_SEGMENT = 0x1
_LC_SYMTAB = 0x2
_LC_ID_DYLIB = 0xD
_LC_LOAD_DYLIB = 0xC
_LC_REEXPORT_DYLIB = 0x8000001F
_LC_SEGMENT_64 = 0x19
_LC_VERSION_MIN_MACOSX = 0x24
_LC_BUILD_VERSION = 0x32

# Resource limits to prevent DoS via crafted binaries
_MAX_LOAD_CMDS = 65_536
_MAX_SYMBOLS = 500_000
_MAX_STRTAB_SIZE = 128 * 1024 * 1024  # 128 MB

# nlist symbol type flags
_N_EXT = 0x01
_N_TYPE_MASK = 0x0E
_N_SECT = 0x0E
_N_UNDF = 0x00

# nlist description flags
_N_WEAK_DEF = 0x0080


def _version_str(packed: int) -> str:
    """Convert packed Mach-O version (xxxx.yy.zz) to string."""
    major = (packed >> 16) & 0xFFFF
    minor = (packed >> 8) & 0xFF
    patch = packed & 0xFF
    return f"{major}.{minor}.{patch}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_macho_metadata(dylib_path: Path) -> MachoMetadata:
    """Extract Mach-O export/import metadata from *dylib_path*.

    Uses a minimal pure-Python parser for Mach-O headers and load commands.
    For fat/universal binaries, analyzes the first architecture slice.

    Returns an empty ``MachoMetadata`` on any parse error (logged as WARNING).
    """
    try:
        with open(dylib_path, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                log.warning("parse_macho_metadata: not a regular file: %s", dylib_path)
                return MachoMetadata()

            return _parse(f, dylib_path)
    except (OSError, ValueError, struct.error) as exc:
        log.warning("parse_macho_metadata: failed to parse %s: %s", dylib_path, exc)
        return MachoMetadata()


def _parse(f: Any, dylib_path: Path) -> MachoMetadata:
    """Parse a single-arch Mach-O file from an open file handle."""
    meta = MachoMetadata()

    magic = f.read(4)
    if magic in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        # Fat/universal binary — parse first slice only
        return _parse_fat(f, dylib_path, magic)

    if magic in (b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"):
        is_64 = True
    elif magic in (b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe"):
        is_64 = False
    else:
        log.warning("parse_macho_metadata: not a Mach-O file: %s", dylib_path)
        return meta

    # Determine endianness
    big_endian = magic in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf")
    endian = ">" if big_endian else "<"

    # Parse Mach-O header
    if is_64:
        hdr_fmt = f"{endian}IIIiIII"  # cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved
        hdr_size = 32  # 4 (magic) + 28
    else:
        hdr_fmt = f"{endian}IIIiIII"[:-1]  # no reserved field
        hdr_fmt = f"{endian}IIIiII"
        hdr_size = 28  # 4 (magic) + 24

    hdr_data = f.read(hdr_size - 4)  # magic already read
    if len(hdr_data) < hdr_size - 4:
        return meta

    hdr = struct.unpack(hdr_fmt, hdr_data)
    cputype = hdr[0]
    filetype = hdr[2]
    ncmds = hdr[3]
    if ncmds > _MAX_LOAD_CMDS:
        raise ValueError(f"ncmds={ncmds} exceeds sanity limit {_MAX_LOAD_CMDS}, possible corrupt/malicious file")
    flags = hdr[5] if len(hdr) > 5 else 0

    meta.cpu_type = _CPU_TYPE_NAMES.get(cputype, f"0x{cputype:x}")
    meta.filetype = _FILETYPE_NAMES.get(filetype, f"0x{filetype:x}")
    meta.flags = flags

    # Parse load commands
    symtab_offset = 0
    symtab_nsyms = 0
    strtab_offset = 0
    strtab_size = 0

    for _ in range(ncmds):
        cmd_pos = f.tell()
        cmd_hdr = f.read(8)
        if len(cmd_hdr) < 8:
            break
        cmd, cmdsize = struct.unpack(f"{endian}II", cmd_hdr)
        # Guard against malformed load command sizes to prevent infinite loops
        if cmdsize < 8:
            log.warning("parse_macho_metadata: invalid cmdsize=%d at offset, stopping", cmdsize)
            break

        if cmd == _LC_ID_DYLIB:
            meta.install_name, meta.current_version, meta.compat_version = \
                _parse_dylib_command(f, cmd_pos, cmdsize, endian)

        elif cmd == _LC_LOAD_DYLIB:
            name, _, _ = _parse_dylib_command(f, cmd_pos, cmdsize, endian)
            if name:
                meta.dependent_libs.append(name)

        elif cmd == _LC_REEXPORT_DYLIB:
            name, _, _ = _parse_dylib_command(f, cmd_pos, cmdsize, endian)
            if name:
                meta.reexported_libs.append(name)

        elif cmd == _LC_SYMTAB:
            # struct symtab_command { cmd, cmdsize, symoff, nsyms, stroff, strsize }
            symtab_data = f.read(16)
            if len(symtab_data) >= 16:
                symtab_offset, symtab_nsyms, strtab_offset, strtab_size = \
                    struct.unpack(f"{endian}IIII", symtab_data)

        elif cmd == _LC_VERSION_MIN_MACOSX:
            ver_data = f.read(8)
            if len(ver_data) >= 4:
                version = struct.unpack(f"{endian}I", ver_data[:4])[0]
                meta.min_os_version = _version_str(version)

        elif cmd == _LC_BUILD_VERSION:
            # struct build_version_command { cmd, cmdsize, platform, minos, sdk, ntools }
            bv_data = f.read(16)
            if len(bv_data) >= 8:
                _platform, minos = struct.unpack(f"{endian}II", bv_data[:8])
                meta.min_os_version = _version_str(minos)

        # Seek to next load command
        f.seek(cmd_pos + cmdsize)

    # Parse symbol table for exports
    if symtab_offset and symtab_nsyms and strtab_offset:
        meta.exports = _parse_symtab(
            f, symtab_offset, symtab_nsyms,
            strtab_offset, strtab_size,
            is_64, endian,
        )

    return meta


def _parse_dylib_command(
    f: Any, cmd_pos: int, cmdsize: int, endian: str,
) -> tuple[str, str, str]:
    """Parse an LC_*_DYLIB command, returning (name, current_version, compat_version)."""
    # struct dylib_command: cmd(4), cmdsize(4), name_offset(4), timestamp(4),
    #                       current_version(4), compat_version(4)
    # We've already read cmd+cmdsize (8 bytes)
    dylib_data = f.read(16)
    if len(dylib_data) < 16:
        return "", "", ""

    name_offset, _timestamp, cur_ver, compat_ver = struct.unpack(
        f"{endian}IIII", dylib_data,
    )

    # Name string starts at cmd_pos + name_offset
    f.seek(cmd_pos + name_offset)
    remaining = cmdsize - name_offset
    if remaining <= 0:
        return "", _version_str(cur_ver), _version_str(compat_ver)

    name_bytes = f.read(remaining)
    name = name_bytes.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    return name, _version_str(cur_ver), _version_str(compat_ver)


def _parse_symtab(
    f: Any,
    symtab_offset: int, nsyms: int,
    strtab_offset: int, strtab_size: int,
    is_64: bool, endian: str,
) -> list[MachoExport]:
    """Parse the LC_SYMTAB symbol table and extract exported symbols."""
    # Guard against malformed/malicious binaries
    if nsyms > _MAX_SYMBOLS:
        log.warning("parse_macho_metadata: nsyms=%d exceeds limit %d, truncating", nsyms, _MAX_SYMBOLS)
        nsyms = _MAX_SYMBOLS
    if strtab_size > _MAX_STRTAB_SIZE:
        log.warning("parse_macho_metadata: strtab_size=%d exceeds limit, truncating", strtab_size)
        strtab_size = _MAX_STRTAB_SIZE

    # Read string table
    f.seek(strtab_offset)
    strtab = f.read(strtab_size)

    # Read symbol table entries
    # struct nlist_64: n_strx(4), n_type(1), n_sect(1), n_desc(2), n_value(8)
    # struct nlist:    n_strx(4), n_type(1), n_sect(1), n_desc(2), n_value(4)
    entry_size = 16 if is_64 else 12
    f.seek(symtab_offset)
    symdata = f.read(nsyms * entry_size)

    exports: list[MachoExport] = []

    for i in range(nsyms):
        offset = i * entry_size
        if offset + entry_size > len(symdata):
            break

        if is_64:
            n_strx, n_type, _n_sect, n_desc = struct.unpack(
                f"{endian}IBBH", symdata[offset:offset + 8],
            )
        else:
            n_strx, n_type, _n_sect, n_desc = struct.unpack(
                f"{endian}IBBH", symdata[offset:offset + 8],
            )

        # Only exported symbols: N_EXT set and defined (N_SECT type, not N_UNDF)
        if not (n_type & _N_EXT):
            continue
        if (n_type & _N_TYPE_MASK) == _N_UNDF:
            continue

        # Extract name from string table — use try/except for O(n) total scan
        if n_strx >= len(strtab):
            continue
        try:
            end = strtab.index(b"\x00", n_strx)
        except ValueError:
            end = len(strtab)
        name = strtab[n_strx:end].decode("utf-8", errors="replace")

        # Strip leading underscore (Mach-O C symbol convention)
        if name.startswith("_"):
            name = name[1:]

        is_weak = bool(n_desc & _N_WEAK_DEF)
        sym_type = MachoSymbolType.WEAK if is_weak else MachoSymbolType.EXPORTED

        exports.append(MachoExport(
            name=name,
            sym_type=sym_type,
            is_weak=is_weak,
        ))

    return exports


def _parse_fat(f: Any, dylib_path: Path, magic: bytes) -> MachoMetadata:
    """Parse a fat/universal binary — extract metadata from the first slice."""
    big_endian = magic == b"\xca\xfe\xba\xbe"
    endian = ">" if big_endian else "<"

    nfat_arch = struct.unpack(f"{endian}I", f.read(4))[0]
    if nfat_arch == 0:
        return MachoMetadata()

    # Read first fat_arch entry: cputype(4), cpusubtype(4), offset(4), size(4), align(4)
    arch_data = f.read(20)
    if len(arch_data) < 20:
        return MachoMetadata()

    _cputype, _cpusubtype, offset, _size, _align = struct.unpack(
        f"{endian}IIIII", arch_data,
    )

    # Seek to the first slice and parse it
    f.seek(offset)
    return _parse(f, dylib_path)
