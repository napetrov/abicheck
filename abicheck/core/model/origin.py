"""Origin enum — evidence source tags for FactSet facts.

Using IntEnum (not str Enum) to eliminate per-fact heap allocation.
At millions-of-facts scale, string origins cost ~500MB+ in __dict__ overhead.
"""
from __future__ import annotations

from enum import IntEnum
from typing import ClassVar


class Origin(IntEnum):
    """Evidence source that produced a fact or detected a change.

    Priority order (highest confidence first):
        CASTXML(1.0) > DWARF(0.9) > PDB(0.8) > ELF/MACHO/COFF(0.7) > BTF/CTF(0.6)

    Note: PDB has higher confidence than ELF — PDB contains full debug type info,
    whereas ELF symbol tables carry only symbol names and addresses.

    IntEnum values encode source identity only, NOT confidence order.
    Always use `.confidence` for ordering decisions.
    """
    CASTXML = 0   # source AST via castxml — highest confidence
    DWARF   = 1   # DWARF debug info
    ELF     = 2   # ELF symbol table / dynamic section
    PDB     = 3   # Windows PDB debug info (higher confidence than ELF)
    MACHO   = 4   # Mach-O metadata
    COFF    = 5   # PE/COFF export table
    BTF     = 6   # BPF Type Format
    CTF     = 7   # Compact Type Format (Solaris/FreeBSD)

    # Class-level constant — avoids rebuilding the dict on every property call
    _CONFIDENCE: ClassVar[dict[int, float]]

    @property
    def confidence(self) -> float:
        """Confidence score 0.0–1.0 (higher = more reliable for ABI analysis)."""
        return Origin._CONFIDENCE[self.value]

    @classmethod
    def highest(cls, origins: tuple[Origin, ...]) -> Origin:
        """Return the highest-confidence origin from a tuple.

        Uses confidence scores, NOT IntEnum integer values.
        """
        if not origins:
            raise ValueError("origins must be non-empty")
        return max(origins, key=lambda o: o.confidence)


# Populated after class definition so Origin members are resolvable
Origin._CONFIDENCE = {
    Origin.CASTXML.value: 1.0,
    Origin.DWARF.value:   0.9,
    Origin.PDB.value:     0.8,   # PDB has type info → higher than ELF
    Origin.ELF.value:     0.7,
    Origin.MACHO.value:   0.7,
    Origin.COFF.value:    0.7,
    Origin.BTF.value:     0.6,
    Origin.CTF.value:     0.6,
}
