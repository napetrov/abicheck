"""DWARF-aware type layout extraction via pyelftools.

Reads DWARF debug info from a compiled .so to extract:
- Struct/class/union sizes and field layouts (offsets, types)
- Enum underlying types and member values
- Alignment information

Requires binaries compiled with -g (DWARF debug info).
If DWARF is absent, returns empty DwarfMetadata gracefully.

See docs/adr/001-technology-stack.md — Sprint 3 layer.
"""
from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FieldInfo:
    """One field (member) inside a struct/union/class."""
    name: str
    type_name: str      # human-readable type (e.g. "int", "MyStruct *")
    byte_offset: int    # DW_AT_data_member_location
    byte_size: int      # size of the field's type (0 if unknown)
    bit_offset: int = 0 # for bitfields: bit offset within the byte
    bit_size: int   = 0 # for bitfields: width in bits (0 = not a bitfield)


@dataclass
class StructLayout:
    """Size and field layout of a struct/class/union."""
    name: str
    byte_size: int                         # DW_AT_byte_size
    alignment: int = 0                     # DW_AT_alignment (DWARF 5; 0 = unknown)
    fields: list[FieldInfo] = field(default_factory=list)
    is_union: bool = False


@dataclass
class EnumInfo:
    """Enum type: underlying integer type + all named members."""
    name: str
    underlying_byte_size: int              # size of the underlying type
    members: dict[str, int] = field(default_factory=dict)  # name → value


@dataclass
class DwarfMetadata:
    """All DWARF-derived ABI-relevant type information from one .so."""
    # name → StructLayout  (structs, classes, unions with external linkage)
    structs: dict[str, StructLayout] = field(default_factory=dict)
    # name → EnumInfo
    enums: dict[str, EnumInfo] = field(default_factory=dict)
    has_dwarf: bool = False   # False = binary had no DWARF info


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_dwarf_metadata(so_path: Path) -> DwarfMetadata:
    """Extract DWARF type layout metadata from *so_path*.

    Returns empty DwarfMetadata (has_dwarf=False) if the binary has no
    debug info or cannot be parsed. Never raises.
    """
    try:
        with open(so_path, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                log.warning("parse_dwarf_metadata: not a regular file: %s", so_path)
                return DwarfMetadata()
            return _parse(f, so_path)
    except (ELFError, OSError, ValueError) as exc:
        log.warning("parse_dwarf_metadata: failed to open/parse %s: %s", so_path, exc)
        return DwarfMetadata()


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------

def _parse(f: object, so_path: Path) -> DwarfMetadata:  # noqa: ANN001
    meta = DwarfMetadata()
    elf = ELFFile(f)  # type: ignore[no-untyped-call]

    if not elf.has_dwarf_info():  # type: ignore[no-untyped-call]
        log.debug("parse_dwarf_metadata: no DWARF info in %s", so_path)
        return meta

    meta.has_dwarf = True
    dwarf = elf.get_dwarf_info()  # type: ignore[no-untyped-call]

    for CU in dwarf.iter_CUs():  # type: ignore[no-untyped-call]
        try:
            _process_cu(CU, meta)
        except Exception as exc:  # noqa: BLE001
            log.warning("parse_dwarf_metadata: skipping CU in %s: %s", so_path, exc)

    return meta


def _process_cu(CU: object, meta: DwarfMetadata) -> None:  # noqa: ANN001
    """Walk all DIEs in one Compilation Unit and collect type info."""
    top_die = CU.get_top_DIE()  # type: ignore[union-attr]
    _walk_die(top_die, meta, CU)


def _walk_die(die: object, meta: DwarfMetadata, CU: object) -> None:  # noqa: ANN001
    tag = die.tag  # type: ignore[union-attr]

    if tag in ("DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"):
        _process_struct(die, meta, CU)
    elif tag == "DW_TAG_enumeration_type":
        _process_enum(die, meta, CU)
    elif tag == "DW_TAG_typedef":
        # C typedef: the underlying type may be anonymous.
        # Resolve the typedef's target and process it with the typedef name.
        _process_typedef(die, meta, CU)

    for child in die.iter_children():  # type: ignore[union-attr]
        _walk_die(child, meta, CU)


def _process_typedef(die: object, meta: DwarfMetadata, CU: object) -> None:  # noqa: ANN001
    """If a typedef points to an anonymous struct/enum, register it under the typedef name."""
    typedef_name = _attr_str(die, "DW_AT_name")
    if not typedef_name:
        return
    if "DW_AT_type" not in die.attributes:  # type: ignore[union-attr]
        return
    try:
        ref = die.attributes["DW_AT_type"].value  # type: ignore[union-attr]
        target = CU.get_DIE_from_refaddr(ref)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return

    tag = target.tag  # type: ignore[union-attr]
    target_name = _attr_str(target, "DW_AT_name")

    if tag in ("DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"):
        if not target_name and typedef_name not in meta.structs:
            # Anonymous struct typedef — use typedef name
            _process_struct_named(target, meta, CU, override_name=typedef_name)
    elif tag == "DW_TAG_enumeration_type":
        if not target_name and typedef_name not in meta.enums:
            _process_enum_named(target, meta, CU, override_name=typedef_name)


# ---------------------------------------------------------------------------
# Struct / class / union
# ---------------------------------------------------------------------------

def _process_struct(die: object, meta: DwarfMetadata, CU: object) -> None:  # noqa: ANN001
    name = _attr_str(die, "DW_AT_name")
    if not name:
        return  # anonymous — handled via typedef in _process_typedef
    _process_struct_named(die, meta, CU, override_name=None)


def _process_struct_named(
    die: object,
    meta: DwarfMetadata,
    CU: object,
    override_name: str | None,
) -> None:
    name = override_name or _attr_str(die, "DW_AT_name")
    if not name:
        return

    byte_size = _attr_int(die, "DW_AT_byte_size")
    if byte_size == 0:
        return  # declaration-only (DW_AT_declaration) — no layout

    is_union = die.tag == "DW_TAG_union_type"  # type: ignore[union-attr]
    alignment = _attr_int(die, "DW_AT_alignment")  # DWARF 5; 0 if absent

    layout = StructLayout(
        name=name,
        byte_size=byte_size,
        alignment=alignment,
        is_union=is_union,
    )

    for child in die.iter_children():  # type: ignore[union-attr]
        if child.tag == "DW_TAG_member":  # type: ignore[union-attr]
            fi = _process_member(child, CU)
            if fi is not None:
                layout.fields.append(fi)

    # Keep only the first definition (ODR: one definition rule).
    if name not in meta.structs:
        meta.structs[name] = layout


def _process_member(die: object, CU: object) -> FieldInfo | None:  # noqa: ANN001
    name = _attr_str(die, "DW_AT_name")
    if not name:
        return None  # padding / anonymous member

    # Byte offset — DW_AT_data_member_location can be a simple int or a block expr
    byte_offset = 0
    if "DW_AT_data_member_location" in die.attributes:  # type: ignore[union-attr]
        attr = die.attributes["DW_AT_data_member_location"]  # type: ignore[union-attr]
        val = attr.value
        if isinstance(val, int):
            byte_offset = val
        elif isinstance(val, list):
            # DW_OP_plus_uconst expression: [DW_OP_plus_uconst, offset]
            byte_offset = int(val[-1]) if val else 0

    # Bit fields
    bit_offset = _attr_int(die, "DW_AT_bit_offset")
    bit_size   = _attr_int(die, "DW_AT_bit_size")

    # Resolve type name and size
    type_name, field_byte_size = _resolve_type(die, CU)

    return FieldInfo(
        name=name,
        type_name=type_name,
        byte_offset=byte_offset,
        byte_size=field_byte_size,
        bit_offset=bit_offset,
        bit_size=bit_size,
    )


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

def _process_enum(die: object, meta: DwarfMetadata, CU: object) -> None:  # noqa: ANN001
    name = _attr_str(die, "DW_AT_name")
    if not name:
        return  # anonymous — handled via typedef in _process_typedef
    _process_enum_named(die, meta, CU, override_name=None)


def _process_enum_named(
    die: object,
    meta: DwarfMetadata,
    CU: object,
    override_name: str | None,
) -> None:
    name = override_name or _attr_str(die, "DW_AT_name")
    if not name:
        return

    byte_size = _attr_int(die, "DW_AT_byte_size")
    if byte_size == 0:
        return  # declaration-only

    enum = EnumInfo(name=name, underlying_byte_size=byte_size)

    for child in die.iter_children():  # type: ignore[union-attr]
        if child.tag == "DW_TAG_enumerator":  # type: ignore[union-attr]
            member_name = _attr_str(child, "DW_AT_name")
            member_val  = _attr_int(child, "DW_AT_const_value")
            if member_name:
                enum.members[member_name] = member_val

    if name not in meta.enums:
        meta.enums[name] = enum


# ---------------------------------------------------------------------------
# Type resolution helpers
# ---------------------------------------------------------------------------

def _resolve_type(die: object, CU: object) -> tuple[str, int]:  # noqa: ANN001
    """Return (type_name, byte_size) for the type referenced by *die*."""
    if "DW_AT_type" not in die.attributes:  # type: ignore[union-attr]
        return ("unknown", 0)
    try:
        ref_addr = die.attributes["DW_AT_type"].value  # type: ignore[union-attr]
        type_die = CU.get_DIE_from_refaddr(ref_addr)  # type: ignore[union-attr]
        return _die_to_type_info(type_die, CU, depth=0)
    except Exception:  # noqa: BLE001
        return ("unknown", 0)


def _die_to_type_info(  # noqa: PLR0911
    die: object,
    CU: object,
    depth: int,
) -> tuple[str, int]:
    """Recursively resolve a type DIE to (name, byte_size). depth limit = 8."""
    if depth > 8:
        return ("...", 0)

    tag = die.tag  # type: ignore[union-attr]

    if tag == "DW_TAG_base_type":
        name = _attr_str(die, "DW_AT_name") or "base"
        size = _attr_int(die, "DW_AT_byte_size")
        return (name, size)

    if tag in ("DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"):
        name = _attr_str(die, "DW_AT_name") or "<anon>"
        size = _attr_int(die, "DW_AT_byte_size")
        return (f"struct {name}" if tag == "DW_TAG_structure_type" else name, size)

    if tag == "DW_TAG_enumeration_type":
        name = _attr_str(die, "DW_AT_name") or "<enum>"
        size = _attr_int(die, "DW_AT_byte_size")
        return (f"enum {name}", size)

    if tag == "DW_TAG_pointer_type":
        if "DW_AT_type" in die.attributes:  # type: ignore[union-attr]
            try:
                ref = die.attributes["DW_AT_type"].value  # type: ignore[union-attr]
                inner_die = CU.get_DIE_from_refaddr(ref)  # type: ignore[union-attr]
                inner_name, _ = _die_to_type_info(inner_die, CU, depth + 1)
                ptr_size = _attr_int(die, "DW_AT_byte_size") or 8
                return (f"{inner_name} *", ptr_size)
            except Exception:  # noqa: BLE001
                pass
        return ("void *", _attr_int(die, "DW_AT_byte_size") or 8)

    if tag in ("DW_TAG_const_type", "DW_TAG_volatile_type", "DW_TAG_restrict_type"):
        if "DW_AT_type" in die.attributes:  # type: ignore[union-attr]
            try:
                ref = die.attributes["DW_AT_type"].value  # type: ignore[union-attr]
                inner_die = CU.get_DIE_from_refaddr(ref)  # type: ignore[union-attr]
                inner_name, size = _die_to_type_info(inner_die, CU, depth + 1)
                qualifier = tag.split("_")[2].lower()  # const/volatile/restrict
                return (f"{qualifier} {inner_name}", size)
            except Exception:  # noqa: BLE001
                pass

    if tag == "DW_TAG_typedef":
        name = _attr_str(die, "DW_AT_name")
        if "DW_AT_type" in die.attributes:  # type: ignore[union-attr]
            try:
                ref = die.attributes["DW_AT_type"].value  # type: ignore[union-attr]
                inner_die = CU.get_DIE_from_refaddr(ref)  # type: ignore[union-attr]
                inner_name, size = _die_to_type_info(inner_die, CU, depth + 1)
                return (name or inner_name, size)
            except Exception:  # noqa: BLE001
                pass
        return (name or "typedef", 0)

    if tag == "DW_TAG_array_type":
        size = _attr_int(die, "DW_AT_byte_size")
        if "DW_AT_type" in die.attributes:  # type: ignore[union-attr]
            try:
                ref = die.attributes["DW_AT_type"].value  # type: ignore[union-attr]
                inner_die = CU.get_DIE_from_refaddr(ref)  # type: ignore[union-attr]
                inner_name, _ = _die_to_type_info(inner_die, CU, depth + 1)
                return (f"{inner_name}[]", size)
            except Exception:  # noqa: BLE001
                pass
        return ("array", size)

    # Fallback
    name = _attr_str(die, "DW_AT_name")
    size = _attr_int(die, "DW_AT_byte_size")
    return (name or tag or "unknown", size)


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------

def _attr_str(die: object, attr: str) -> str:
    """Return string value of a DIE attribute, or ''."""
    attrs = die.attributes  # type: ignore[union-attr]
    if attr not in attrs:
        return ""
    val = attrs[attr].value
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val) if val is not None else ""


def _attr_int(die: object, attr: str) -> int:
    """Return integer value of a DIE attribute, or 0."""
    attrs = die.attributes  # type: ignore[union-attr]
    if attr not in attrs:
        return 0
    val = attrs[attr].value
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0
