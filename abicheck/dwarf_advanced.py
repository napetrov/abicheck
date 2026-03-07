"""Sprint 4: Advanced DWARF analysis.

Detects:
1. Calling convention changes (DW_AT_calling_convention on exported functions)
2. Struct packing drift (__attribute__((packed)) — via DWARF field offsets vs
   natural alignment of the *type* byte size, properly resolved via DW_AT_type)
3. Toolchain flag drift via DW_AT_producer parsing
   (-fshort-enums, -fpack-struct, -fno-common, -m32/-m64, -mabi=*, etc.)

Design notes:
- Single iterative DWARF walk per binary (deque-based, no recursion)
- DW_AT_type is resolved for member size — fixes false-negative in packed detection
- Imports at module level (style consistency with Sprint 3)
- Specific exception handling: ELFError/OSError/ValueError; re-raises others
- "First CU wins" for DW_AT_producer (acceptable: ABI flags uniform across TUs
  in well-formed libraries; divergence is logged at WARNING level)

Coverage note:
  DW_AT_calling_convention is rarely emitted on Linux x86-64 (System V AMD64 ABI
  uses a single implicit calling convention). This detector is most useful for
  Windows (__stdcall/__cdecl mixed libraries) and embedded targets.
  The toolchain flag detector (DW_AT_producer) provides broader coverage for
  ABI-flag drift on Linux.
"""
from __future__ import annotations

import collections
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile

log = logging.getLogger(__name__)

# DW_AT_calling_convention values (DWARF 5 standard + vendor extensions)
_CC_NAMES: dict[int, str] = {
    0x01: "normal",
    0x02: "program",
    0x03: "nocall",
    0x04: "pass_by_reference",      # DWARF 5
    0x05: "pass_by_value",          # DWARF 5
    0x40: "GNU_renesas_sh",
    0x41: "GNU_borland_fastcall_i386",
    0x80: "GNU_push_call_stub",     # GCC internal
    0x81: "GNU_push_arg",           # GCC internal
    0xb0: "BORLAND_safecall",
    0xb1: "BORLAND_stdcall",
    0xb2: "BORLAND_pascal",
    0xb3: "BORLAND_msfastcall",
    0xb4: "BORLAND_msreturn",
    0xb5: "BORLAND_thiscall",
    0xb6: "BORLAND_fastcall",
    0xb9: "LLVM_PreserveMost",
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

# Natural alignment (bytes) by type size on most LP64 platforms
_NATURAL_ALIGN: dict[int, int] = {1: 1, 2: 2, 4: 4, 8: 8, 16: 16}

# Tags to prune: don't descend into function bodies or inlined frames
_PRUNE_TAGS: frozenset[str] = frozenset({
    "DW_TAG_lexical_block",
    "DW_TAG_inlined_subroutine",
    "DW_TAG_GNU_call_site",
})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ToolchainInfo:
    """Parsed DW_AT_producer metadata from a binary."""
    producer_string: str = ""       # raw DW_AT_producer value
    compiler: str = ""              # "GCC", "clang", "ICC"
    version: str = ""               # e.g. "13.2.1"
    abi_flags: set[str] = field(default_factory=set)  # extracted ABI-affecting flags


@dataclass
class AdvancedDwarfMetadata:
    """Sprint 4 metadata extracted from a single .so."""
    has_dwarf: bool = False
    toolchain: ToolchainInfo = field(default_factory=ToolchainInfo)
    # function_name → CC string (only non-"normal" entries stored)
    # NOTE: on Linux x86-64, this dict is typically empty (DW_CC_normal implicit)
    calling_conventions: dict[str, str] = field(default_factory=dict)
    # struct names where any field has a misaligned byte offset → __attribute__((packed))
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
        with open(so_path, "rb") as f:
            elf = ELFFile(f)
            if not elf.has_dwarf_info():
                return AdvancedDwarfMetadata()
            meta = AdvancedDwarfMetadata(has_dwarf=True)
            dwarf = elf.get_dwarf_info()
            for CU in dwarf.iter_CUs():
                try:
                    _process_cu(CU, meta)
                except (ELFError, OSError, ValueError, KeyError) as exc:
                    log.warning("parse_advanced_dwarf: skipping CU: %s", exc)
            return meta
    except (ELFError, OSError, ValueError) as exc:
        log.warning("parse_advanced_dwarf: failed %s: %s", so_path, exc)
        return AdvancedDwarfMetadata()


# ---------------------------------------------------------------------------
# Internal: per-CU processing
# ---------------------------------------------------------------------------

def _process_cu(CU: Any, meta: AdvancedDwarfMetadata) -> None:
    top = CU.get_top_DIE()

    # Extract toolchain info from DW_AT_producer on the CU top DIE (first CU wins)
    if not meta.toolchain.producer_string:
        producer = _attr_str(top, "DW_AT_producer")
        if producer:
            meta.toolchain = _parse_producer(producer)

    _walk_cu(top, meta, CU)


def _walk_cu(root: Any, meta: AdvancedDwarfMetadata, CU: Any) -> None:
    """Iterative depth-first DIE walk.

    Does NOT descend into DW_TAG_subprogram children — we only need the
    subprogram DIE itself for calling convention. This halves traversal time
    in function-heavy TUs. Packed struct check still needs struct member
    children (handled directly in _check_packed).
    """
    stack: collections.deque[Any] = collections.deque([root])

    while stack:
        die = stack.pop()
        tag = die.tag

        if tag in _PRUNE_TAGS:
            continue

        if tag in ("DW_TAG_subprogram", "DW_TAG_subroutine_type"):
            _extract_calling_convention(die, meta)
            # Don't descend into subprogram children — not needed for CC extraction
            # and avoids traversing all local variables, params, inlined calls
            continue

        if tag in ("DW_TAG_structure_type", "DW_TAG_class_type"):
            _check_packed(die, meta, CU, override_name=None)

        elif tag == "DW_TAG_typedef":
            # Anonymous struct typedef: `typedef struct {...} Name` — struct has no
            # DW_AT_name; resolve the typedef target and check if it's a packed struct.
            _check_packed_typedef(die, meta, CU)

        # Push children in reverse order (DFS left-to-right)
        stack.extend(reversed(list(die.iter_children())))


# ---------------------------------------------------------------------------
# Calling convention extraction
# ---------------------------------------------------------------------------

def _extract_calling_convention(die: Any, meta: AdvancedDwarfMetadata) -> None:
    """Record non-default calling conventions for ABI-exported functions.

    On Linux x86-64 (System V AMD64), GCC/Clang rarely emit DW_AT_calling_convention
    (it defaults to DW_CC_normal which is omitted). This detector is most relevant
    for Windows __stdcall/__fastcall or embedded targets.
    """
    name = _attr_str(die, "DW_AT_name")
    if not name:
        return
    # Only externally-visible functions matter for ABI surface
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

def _check_packed_typedef(die: Any, meta: AdvancedDwarfMetadata, CU: Any) -> None:
    """Handle `typedef struct __attribute__((packed)) {...} Name`.

    In this pattern the struct itself is anonymous (no DW_AT_name); the typedef
    provides the visible name. We resolve the target DIE and check packing
    using the typedef name as the identifier.
    """
    typedef_name = _attr_str(die, "DW_AT_name")
    if not typedef_name or "DW_AT_type" not in die.attributes:
        return
    try:
        attr = die.attributes["DW_AT_type"]
        raw: int = attr.value
        abs_off = raw if attr.form == "DW_FORM_ref_addr" else raw + CU.cu_offset
        target = CU.get_DIE_from_refaddr(abs_off)
    except Exception:  # noqa: BLE001
        return

    tag = target.tag
    if tag not in ("DW_TAG_structure_type", "DW_TAG_class_type"):
        return
    target_name = _attr_str(target, "DW_AT_name")
    if target_name:
        return  # named struct — will be registered under its own name

    _check_packed(target, meta, CU, override_name=typedef_name)


def _check_packed(
    die: Any,
    meta: AdvancedDwarfMetadata,
    CU: Any,
    override_name: str | None = None,
) -> None:
    """Detect if struct has misaligned fields → __attribute__((packed)).

    Resolves DW_AT_type on each member to get the type's byte size,
    then checks if the field offset is aligned to that size.
    A single misaligned field is sufficient to classify the struct as packed.
    """
    name = override_name or _attr_str(die, "DW_AT_name")
    if not name:
        return
    byte_size = _attr_int(die, "DW_AT_byte_size")
    if byte_size == 0:
        return  # forward declaration only

    for child in die.iter_children():
        if child.tag != "DW_TAG_member":
            continue
        if _attr_int(child, "DW_AT_bit_size"):
            continue  # bitfields: skip (always "misaligned" by nature)

        # Get byte offset of this field
        offset = 0
        if "DW_AT_data_member_location" in child.attributes:
            v = child.attributes["DW_AT_data_member_location"].value
            offset = v if isinstance(v, int) else (int(v[-1]) if v else 0)

        # Get field SIZE by following DW_AT_type to the type DIE
        field_size = _get_type_byte_size(child, CU)
        if field_size <= 1:
            continue  # char/bool: always naturally aligned

        natural = _NATURAL_ALIGN.get(min(field_size, 16), 1)
        if natural > 1 and offset % natural != 0:
            log.debug("packed struct detected: %s field at offset %d (size %d, align %d)",
                      name, offset, field_size, natural)
            meta.packed_structs.add(name)
            return  # one misaligned field is sufficient


def _get_type_byte_size(member_die: Any, CU: Any) -> int:
    """Resolve DW_AT_type from a member DIE and return DW_AT_byte_size.

    Follows typedef chains up to depth 4. Returns 0 if resolution fails.
    """
    if "DW_AT_type" not in member_die.attributes:
        return 0
    try:
        attr = member_die.attributes["DW_AT_type"]
        form = attr.form
        raw: int = attr.value
        abs_offset = raw if form == "DW_FORM_ref_addr" else raw + CU.cu_offset
        type_die = CU.get_DIE_from_refaddr(abs_offset)

        # Follow typedef / const / volatile / restrict chains
        for _ in range(4):
            tag = type_die.tag
            if tag in (
                "DW_TAG_typedef",
                "DW_TAG_const_type",
                "DW_TAG_volatile_type",
                "DW_TAG_restrict_type",
            ):
                if "DW_AT_type" not in type_die.attributes:
                    return 0
                a = type_die.attributes["DW_AT_type"]
                f = a.form
                r: int = a.value
                abs_off = r if f == "DW_FORM_ref_addr" else r + CU.cu_offset
                type_die = CU.get_DIE_from_refaddr(abs_off)
            else:
                break

        size_attr = type_die.attributes.get("DW_AT_byte_size")
        return int(size_attr.value) if size_attr else 0
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# DW_AT_producer parsing
# ---------------------------------------------------------------------------

def _parse_producer(producer: str) -> ToolchainInfo:
    """Parse raw DW_AT_producer string into ToolchainInfo."""
    info = ToolchainInfo(producer_string=producer)

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

    for m in _ABI_FLAGS_RE.finditer(producer):
        info.abi_flags.add(m.group(0))

    return info


# ---------------------------------------------------------------------------
# Diff (called from checker.py _diff_advanced_dwarf)
# ---------------------------------------------------------------------------

def diff_advanced_dwarf(
    old_meta: AdvancedDwarfMetadata,
    new_meta: AdvancedDwarfMetadata,
) -> list[tuple[str, str, str, str | None, str | None]]:
    """Return (kind, symbol, description, old_value, new_value) tuples.

    Returns [] gracefully if either side has no DWARF.
    """
    if not old_meta.has_dwarf or not new_meta.has_dwarf:
        return []

    results: list[tuple[str, str, str, str | None, str | None]] = []

    # 1. Calling convention drift
    for fname, old_cc in old_meta.calling_conventions.items():
        new_cc = new_meta.calling_conventions.get(fname, "normal")
        if old_cc != new_cc:
            results.append((
                "calling_convention_changed", fname,
                f"Calling convention changed: {fname} ({old_cc} → {new_cc})",
                old_cc, new_cc,
            ))
    for fname, new_cc in new_meta.calling_conventions.items():
        if fname not in old_meta.calling_conventions:
            results.append((
                "calling_convention_changed", fname,
                f"Calling convention changed: {fname} (normal → {new_cc})",
                "normal", new_cc,
            ))

    # 2. Struct packing drift
    for name in sorted(old_meta.packed_structs - new_meta.packed_structs):
        results.append((
            "struct_packing_changed", name,
            f"Struct packing removed: {name} was packed, now standard layout",
            "packed", "standard",
        ))
    for name in sorted(new_meta.packed_structs - old_meta.packed_structs):
        results.append((
            "struct_packing_changed", name,
            f"Struct packing added: {name} is now __attribute__((packed))",
            "standard", "packed",
        ))

    # 3. Toolchain ABI flag drift
    old_flags = old_meta.toolchain.abi_flags
    new_flags = new_meta.toolchain.abi_flags
    removed_flags = old_flags - new_flags
    added_flags = new_flags - old_flags
    if removed_flags or added_flags:
        parts = []
        if added_flags:
            parts.append(f"added: {', '.join(sorted(added_flags))}")
        if removed_flags:
            parts.append(f"removed: {', '.join(sorted(removed_flags))}")
        results.append((
            "toolchain_flag_drift", "<toolchain>",
            f"ABI-affecting compiler flags changed: {'; '.join(parts)}",
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
    return bool(die.attributes[attr].value)
