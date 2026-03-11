"""Origin enum — evidence source tags for FactSet facts.

Using IntEnum (not str Enum) to eliminate per-fact heap allocation.
At millions-of-facts scale, string origins cost ~500MB+ in __dict__ overhead.
"""
from __future__ import annotations

from enum import IntEnum


class Origin(IntEnum):
    """Evidence source that produced a fact or detected a change.

    Priority order (highest confidence first):
        CASTXML > DWARF > ELF > PDB > MACHO > COFF > BTF > CTF
    """
    CASTXML = 0   # source AST via castxml — highest confidence
    DWARF   = 1   # DWARF debug info
    ELF     = 2   # ELF symbol table / dynamic section
    PDB     = 3   # Windows PDB debug info
    MACHO   = 4   # Mach-O metadata
    COFF    = 5   # PE/COFF export table
    BTF     = 6   # BPF Type Format
    CTF     = 7   # Compact Type Format (Solaris/FreeBSD)

    @property
    def confidence(self) -> float:
        """Confidence score 0.0–1.0 (higher = more reliable)."""
        _scores = {
            Origin.CASTXML: 1.0,
            Origin.DWARF:   0.9,
            Origin.ELF:     0.7,
            Origin.PDB:     0.8,
            Origin.MACHO:   0.7,
            Origin.COFF:    0.7,
            Origin.BTF:     0.6,
            Origin.CTF:     0.6,
        }
        return _scores[self]

    @classmethod
    def highest(cls, origins: tuple[Origin, ...]) -> Origin:
        """Return the highest-confidence origin from a tuple."""
        if not origins:
            raise ValueError("origins must be non-empty")
        return min(origins, key=lambda o: o.value)
