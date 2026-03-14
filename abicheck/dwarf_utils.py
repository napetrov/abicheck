"""Shared DWARF attribute helpers for pyelftools DIE access.

Used by dwarf_metadata.py, dwarf_advanced.py, and dwarf_unified.py to avoid
duplicating low-level DIE attribute extraction logic.
"""
from __future__ import annotations

from typing import Any


def attr_str(die: Any, attr: str) -> str:
    """Return string value of a DIE attribute, or ''."""
    if attr not in die.attributes:
        return ""
    val = die.attributes[attr].value
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val) if val is not None else ""


def attr_int(die: Any, attr: str) -> int:
    """Return integer value of a DIE attribute, or 0.

    Handles signed DW_FORM_sdata values correctly (e.g. negative enum consts).
    """
    if attr not in die.attributes:
        return 0
    val = die.attributes[attr].value
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def attr_bool(die: Any, attr: str) -> bool:
    """Return boolean value of a DIE attribute, or False."""
    if attr not in die.attributes:
        return False
    return bool(die.attributes[attr].value)


def resolve_die_ref(die: Any, attr_name: str, CU: Any) -> Any:
    """Resolve a DW_AT_type (or similar) reference to the target DIE.

    Handles both CU-relative refs (DW_FORM_ref1/2/4/8/udata) and
    section-absolute refs (DW_FORM_ref_addr).  pyelftools stores the raw
    offset in .value; for CU-relative forms we add CU.cu_offset to get
    the absolute .debug_info position expected by get_DIE_from_refaddr().
    """
    attr = die.attributes[attr_name]
    form = attr.form
    raw_val: int = attr.value

    if form == "DW_FORM_ref_addr":
        # Section-relative: already an absolute offset
        abs_offset = raw_val
    else:
        # CU-relative (DW_FORM_ref1/2/4/8/ref_udata): add CU header offset
        abs_offset = raw_val + CU.cu_offset

    return CU.get_DIE_from_refaddr(abs_offset)


def resolve_type_die(die: Any, CU: Any) -> Any | None:
    """Resolve DW_AT_type reference on *die* to a target DIE, or None."""
    if "DW_AT_type" not in die.attributes:
        return None
    try:
        return resolve_die_ref(die, "DW_AT_type", CU)
    except Exception:  # noqa: BLE001
        return None
