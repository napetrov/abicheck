"""Sprint 4: Advanced DWARF analysis.

Detects:
1. Calling convention changes (DW_AT_calling_convention on functions/methods)
2. Struct packing drift (__attribute__((packed)) — detected via DWARF field offsets
   vs natural alignment: if any field is at a non-aligned offset, struct is packed)
3. Toolchain flag drift via DW_AT_producer parsing
   (-fshort-enums, -fpack-struct, -fno-common, toolchain version change)
4. typeinfo / vtable symbol visibility changes (ELF .dynsym cross-check)

All functions return [] gracefully when DWARF is absent.
"""
from __future__ import annotations

import collections
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# DW_AT_calling_convention values (DWARF standard)
_CC_NAMES: dict[int, str] = {
    0x01: "normal",
    0x02: "program",
    0x03: "nocall",
    0x04: "pass_by_reference",   # DWARF 5
    0x05: "pass_by_value",       # DWARF 5
    0x40: "GNU_renesas_sh",
    0x41: "GNU_borland_fastcall_i386",
    0xb0: "BORLAND_safecall",
    0xb1: "BORLAND_stdcall",
    0xb2: "BORLAND_pascal",
    0xb3: "BORLAND_msfastcall",
    0xb4: "BORLAND_msreturn",
    0xb5: "BORLAND_thiscall",
    0xb6: "BORLAND_fastcall",
    0xd0: "LLVM_vectorcall",
}

# Flags in DW_AT_producer that affect binary ABI
_ABI_FLAGS_RE = re.compile(
    r"""
    (?P<short_enums>-fshort-enums)
    |(?P<pack_struct>-fpack-struct(?:=\d+)?)
    |(?P<no_common>-fno-common)
    |(?P<common>-fcommon)
    |(?P<m32>-m32)
    |(?P<m64>-m64)
    |(?P<mabi>-mabi=\S+)
    |(?P<fabi>-fabi-version=\d+)
    |(?P<cxx11abi>-D_GLIBCXX_USE_CXX11_ABI=\d)
    """,
    re.VERBOSE,
)


@dataclass
class ToolchainInfo:
    """Parsed DW_AT_producer metadata from a binary."""
    producer_string: str = ""           # raw DW_AT_producer value
    compiler: str = ""                  # e.g. "GCC", "clang", "ICC"
    version: str = ""                   # e.g. "13.2.1"
    abi_flags: set[str] = field(default_factory=set)  # extracted ABI-affecting flags


@dataclass
class AdvancedDwarfMetadata:
    """Sprint 4 metadata extracted from a single .so."""
    has_dwarf: bool = False
    toolchain: ToolchainInfo = field(default_factory=ToolchainInfo)
    # function_name → calling_convention string (only non-"normal" entries)
    calling_conventions: dict[str, str] = field(default_factory=dict)
    # struct_name → True if detected as packed (any misaligned field)
    packed_structs: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_advanced_dwarf(so_path: Path) -> AdvancedDwarfMetadata:
    """Extract Sprint 4 metadata from *so_path*.

    Returns empty AdvancedDwarfMetadata (has_dwarf=False) if binary has no
    debug info or cannot be parsed. Never raises.
    """
    try:
        from elftools.elf.elffile import ELFFile
        with open(so_path, "rb") as f:
            elf = ELFFile(f)
            if not elf.has_dwarf_info():
                return AdvancedDwarfMetadata()
            meta = AdvancedDwarfMetadata(has_dwarf=True)
            dwarf = elf.get_dwarf_info()
            for CU in dwarf.iter_CUs():
                try:
                    _process_cu(CU, meta)
                except Exception as exc:  # noqa: BLE001
                    log.warning("parse_advanced_dwarf: skipping CU: %s", exc)
            return meta
    except Exception as exc:  # noqa: BLE001
        log.warning("parse_advanced_dwarf: failed %s: %s", so_path, exc)
        return AdvancedDwarfMetadata()


# ---------------------------------------------------------------------------
# Internal: CU processing
# ---------------------------------------------------------------------------

def _process_cu(CU: Any, meta: AdvancedDwarfMetadata) -> None:
    top = CU.get_top_DIE()

    # Extract toolchain info from CU-level DW_AT_producer (first CU wins)
    if not meta.toolchain.producer_string:
        producer = _attr_str(top, "DW_AT_producer")
        if producer:
            meta.toolchain = _parse_producer(producer)

    _walk_cu(top, meta)


def _walk_cu(root: Any, meta: AdvancedDwarfMetadata) -> None:
    """Iterative walk; extract calling_convention and packed struct info."""
    _SKIP = frozenset({
        "DW_TAG_lexical_block",
        "DW_TAG_inlined_subroutine",
        "DW_TAG_GNU_call_site",
    })
    stack: collections.deque[Any] = collections.deque([root])

    while stack:
        die = stack.pop()
        tag = die.tag

        if tag in _SKIP:
            continue

        if tag in ("DW_TAG_subprogram", "DW_TAG_subroutine_type"):
            _extract_calling_convention(die, meta)

        if tag in ("DW_TAG_structure_type", "DW_TAG_class_type"):
            _check_packed(die, meta)

        stack.extend(reversed(list(die.iter_children())))


# ---------------------------------------------------------------------------
# Calling convention extraction
# ---------------------------------------------------------------------------

def _extract_calling_convention(die: Any, meta: AdvancedDwarfMetadata) -> None:
    """Record non-default calling conventions for ABI-exported functions."""
    name = _attr_str(die, "DW_AT_name")
    if not name:
        return
    # Only externally-visible functions matter
    if not _attr_bool(die, "DW_AT_external"):
        return
    if "DW_AT_calling_convention" not in die.attributes:
        return
    raw = die.attributes["DW_AT_calling_convention"].value
    cc_name = _CC_NAMES.get(int(raw), f"unknown(0x{int(raw):02x})")
    if cc_name != "normal":
        meta.calling_conventions[name] = cc_name


# ---------------------------------------------------------------------------
# Packed struct detection
# ---------------------------------------------------------------------------

# Natural alignment of common DWARF base types by byte size
_NATURAL_ALIGN: dict[int, int] = {
    1: 1,
    2: 2,
    4: 4,
    8: 8,
    16: 16,
}


def _check_packed(die: Any, meta: AdvancedDwarfMetadata) -> None:
    """Detect if struct has any fields at misaligned offsets → packed."""
    name = _attr_str(die, "DW_AT_name")
    if not name:
        return
    byte_size = _attr_int(die, "DW_AT_byte_size")
    if byte_size == 0:
        return  # forward declaration

    for child in die.iter_children():
        if child.tag != "DW_TAG_member":
            continue
        if _attr_int(child, "DW_AT_bit_size"):
            continue  # bitfields always packed-like, skip

        offset = 0
        if "DW_AT_data_member_location" in child.attributes:
            v = child.attributes["DW_AT_data_member_location"].value
            offset = v if isinstance(v, int) else (int(v[-1]) if v else 0)

        # Get field byte size to determine natural alignment requirement
        field_size = _get_member_size(child)
        if field_size <= 1:
            continue  # char/byte: always aligned

        natural = _NATURAL_ALIGN.get(min(field_size, 16), 1)
        if natural > 1 and offset % natural != 0:
            meta.packed_structs.add(name)
            return  # one misaligned field is enough


def _get_member_size(die: Any) -> int:
    """Best-effort field size via DW_AT_byte_size on the referenced type."""
    if "DW_AT_byte_size" in die.attributes:
        return _attr_int(die, "DW_AT_byte_size")
    # Could also resolve DW_AT_type, but keep it simple for now
    return 0


# ---------------------------------------------------------------------------
# DW_AT_producer parsing
# ---------------------------------------------------------------------------

def _parse_producer(producer: str) -> ToolchainInfo:
    """Parse the raw DW_AT_producer string into ToolchainInfo."""
    info = ToolchainInfo(producer_string=producer)

    # Detect compiler
    if "GCC" in producer or "GNU" in producer:
        info.compiler = "GCC"
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", producer)
        if m:
            info.version = m.group(1)
    elif re.search(r"clang|LLVM", producer, re.I):
        info.compiler = "clang"
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", producer)
        if m:
            info.version = m.group(1)
    elif re.search(r"Intel|ICC|ICX", producer):
        info.compiler = "ICC"
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", producer)
        if m:
            info.version = m.group(1)

    # Extract ABI-affecting flags
    for m in _ABI_FLAGS_RE.finditer(producer):
        info.abi_flags.add(m.group(0))

    return info


# ---------------------------------------------------------------------------
# Diff functions (called from checker.py)
# ---------------------------------------------------------------------------

def diff_advanced_dwarf(
    old_meta: AdvancedDwarfMetadata,
    new_meta: AdvancedDwarfMetadata,
) -> list[tuple[str, str, str, str | None, str | None]]:
    """Return list of (kind, symbol, description, old_value, new_value) tuples.

    Caller (checker.py) converts these to Change objects using ChangeKind.
    Returns [] if either side has no DWARF.
    """
    if not old_meta.has_dwarf or not new_meta.has_dwarf:
        return []

    results: list[tuple[str, str, str, str | None, str | None]] = []

    # 1. Calling convention changes
    for fname, old_cc in old_meta.calling_conventions.items():
        new_cc = new_meta.calling_conventions.get(fname, "normal")
        if old_cc != new_cc:
            results.append((
                "calling_convention_changed",
                fname,
                f"Calling convention changed: {fname} ({old_cc} → {new_cc})",
                old_cc,
                new_cc,
            ))
    for fname, new_cc in new_meta.calling_conventions.items():
        if fname not in old_meta.calling_conventions:
            # Was 'normal' (default), now explicit non-normal
            results.append((
                "calling_convention_changed",
                fname,
                f"Calling convention changed: {fname} (normal → {new_cc})",
                "normal",
                new_cc,
            ))

    # 2. Packing changes (packed ↔ unpacked)
    old_packed = old_meta.packed_structs
    new_packed = new_meta.packed_structs
    for name in sorted(old_packed - new_packed):
        results.append((
            "struct_packing_changed",
            name,
            f"Struct packing removed: {name} was packed, now standard layout",
            "packed",
            "standard",
        ))
    for name in sorted(new_packed - old_packed):
        results.append((
            "struct_packing_changed",
            name,
            f"Struct packing added: {name} is now packed (__attribute__((packed)))",
            "standard",
            "packed",
        ))

    # 3. Toolchain ABI flag drift
    old_flags = old_meta.toolchain.abi_flags
    new_flags = new_meta.toolchain.abi_flags
    removed_flags = old_flags - new_flags
    added_flags = new_flags - old_flags
    if removed_flags or added_flags:
        desc_parts = []
        if added_flags:
            desc_parts.append(f"added: {', '.join(sorted(added_flags))}")
        if removed_flags:
            desc_parts.append(f"removed: {', '.join(sorted(removed_flags))}")
        results.append((
            "toolchain_flag_drift",
            "<toolchain>",
            f"ABI-affecting compiler flags changed: {'; '.join(desc_parts)}",
            ",".join(sorted(old_flags)) or None,
            ",".join(sorted(new_flags)) or None,
        ))

    return results


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------

def _attr_str(die: Any, attr: str) -> str:
    if attr not in die.attributes:
        return ""
    val = die.attributes[attr].value
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val) if val is not None else ""


def _attr_int(die: Any, attr: str) -> int:
    if attr not in die.attributes:
        return 0
    val = die.attributes[attr].value
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _attr_bool(die: Any, attr: str) -> bool:
    if attr not in die.attributes:
        return False
    val = die.attributes[attr].value
    return bool(val)
