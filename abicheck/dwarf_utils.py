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

"""Shared DWARF attribute helpers for pyelftools DIE access.

Used by dwarf_metadata.py, dwarf_advanced.py, and dwarf_unified.py to avoid
duplicating low-level DIE attribute extraction logic.
"""
# pylint: disable=invalid-name  # CU is the standard DWARF term (Compilation Unit)
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


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

#: Base set of DWARF tags to prune (skip subtrees).
#: Each module extends this with its own additions (e.g. DW_TAG_subprogram).
BASE_PRUNE_TAGS: frozenset[str] = frozenset({
    "DW_TAG_inlined_subroutine",
    "DW_TAG_lexical_block",
    "DW_TAG_GNU_call_site",
})


# ---------------------------------------------------------------------------
# Member location decoding
# ---------------------------------------------------------------------------

def _evaluate_location_expr(expr: list[object]) -> int:
    """Evaluate a DWARF location expression list to a byte offset.

    DWARF ``DW_AT_data_member_location`` can be a list of opcodes/operands
    rather than a plain integer.  Common patterns:
    - ``[DW_OP_plus_uconst, N]`` — offset is N
    - ``[DW_OP_constu, N]`` or ``[DW_OP_consts, N]`` — push N
    - ``[DW_OP_lit0..DW_OP_lit31]`` — push literal 0–31

    We use a minimal stack machine to handle these; fall back to 0 on failure.
    """
    stack: list[int] = [0]  # implicit base address
    i = 0
    items = list(expr)
    while i < len(items):
        item = items[i]
        # pyelftools may emit tuples (opcode, operand, ...)
        if isinstance(item, tuple):
            op = item[0] if len(item) > 0 else 0
            operand = item[1] if len(item) > 1 else 0
            if isinstance(op, int) and isinstance(operand, int):
                # DW_OP_plus_uconst = 0x23
                if op == 0x23:
                    stack[-1] = stack[-1] + operand if stack else operand
                # DW_OP_constu = 0x10, DW_OP_consts = 0x11
                elif op in (0x10, 0x11):
                    stack.append(operand)
                # DW_OP_lit0..DW_OP_lit31 = 0x30..0x4f
                elif 0x30 <= op <= 0x4F:
                    stack.append(op - 0x30)
                # DW_OP_plus = 0x22
                elif op == 0x22 and len(stack) >= 2:
                    b = stack.pop()
                    stack[-1] += b
            i += 1
            continue

        if isinstance(item, int):
            # Raw byte stream: interpret as opcodes
            next_item = items[i + 1] if i + 1 < len(items) else None
            next_int = next_item if isinstance(next_item, int) else None
            # DW_OP_plus_uconst = 0x23
            if item == 0x23 and next_int is not None:
                stack[-1] = stack[-1] + next_int if stack else next_int
                i += 2
                continue
            # DW_OP_constu = 0x10, DW_OP_consts = 0x11
            if item in (0x10, 0x11) and next_int is not None:
                stack.append(next_int)
                i += 2
                continue
            # DW_OP_lit0..DW_OP_lit31 (0x30..0x4f)
            if 0x30 <= item <= 0x4F:
                stack.append(item - 0x30)
                i += 1
                continue
            # DW_OP_plus = 0x22
            if item == 0x22 and len(stack) >= 2:
                b = stack.pop()
                stack[-1] += b
                i += 1
                continue
            # Unknown opcode or bare integer — treat as constant
            stack.append(item)
        i += 1

    return stack[-1] if stack else 0


def decode_member_location(val: int | list[object] | None) -> int:
    """Decode DW_AT_data_member_location to a byte offset.

    Handles all forms produced by different DWARF versions:
    - None → 0
    - Constant integer (DWARF 3+) → value directly
    - Location expression list (DWARF 2/3) → evaluated via stack machine
    """
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    return _evaluate_location_expr(val)


# ---------------------------------------------------------------------------
# DIE reference resolution
# ---------------------------------------------------------------------------

def resolve_type_die(die: Any, CU: Any) -> Any | None:
    """Resolve DW_AT_type reference on *die* to a target DIE, or None."""
    if "DW_AT_type" not in die.attributes:
        return None
    try:
        return resolve_die_ref(die, "DW_AT_type", CU)
    except Exception:  # noqa: BLE001
        return None
