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

"""Lightweight binary fingerprinting for rename detection in stripped binaries.

Exploratory module (see ADR-003 extension).  Uses function size and code hash
from ELF .dynsym + .text to detect likely renames when symbol names change
but the underlying code is identical or near-identical.

This is NOT a reverse-engineering tool — it provides a secondary matching
signal to reduce false "removed + added" churn in symbols-only mode.

Integration point: feed ``RenameCandidate`` results into the diff engine to
convert "removed + added" pairs into "likely renamed" changes.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import Section, SymbolTableSection

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FunctionFingerprint:
    """Fingerprint for a single exported function symbol.

    Attributes:
        name: Symbol name (mangled).
        size: st_size from .dynsym (code size in bytes, 0 if unknown).
        code_hash: SHA-256 hex digest of the function's code bytes from .text,
            or empty string if the code region could not be read.
        section_index: ELF section index the symbol resides in.
    """
    name: str
    size: int
    code_hash: str
    section_index: int = 0


@dataclass(frozen=True)
class SectionSummary:
    """Coarse-grained summary of an ELF section.

    Used for quick triage: if .text didn't change, ABI probably didn't either.
    """
    name: str
    size: int
    content_hash: str  # SHA-256 of raw section bytes


@dataclass(frozen=True)
class BinarySummary:
    """Section-level summary of an entire binary.

    Provides a coarse "binary changed significantly" vs "binary barely changed"
    signal for triage before running full diff.
    """
    sections: dict[str, SectionSummary] = field(default_factory=dict)

    @property
    def text_changed(self) -> bool | None:
        """Return None if no .text info, True/False based on presence."""
        return ".text" in self.sections

    def differs_from(self, other: BinarySummary) -> dict[str, tuple[str, str]]:
        """Return sections that differ between self and other.

        Returns dict of section_name → (old_hash, new_hash) for sections
        present in both but with different content hashes.  Sections only in
        one binary are not included (they indicate structural changes).
        """
        diffs: dict[str, tuple[str, str]] = {}
        common = set(self.sections) & set(other.sections)
        for name in sorted(common):
            old_h = self.sections[name].content_hash
            new_h = other.sections[name].content_hash
            if old_h != new_h:
                diffs[name] = (old_h, new_h)
        return diffs

    @property
    def text_size(self) -> int | None:
        """Return .text section size, or None if absent."""
        s = self.sections.get(".text")
        return s.size if s is not None else None


@dataclass(frozen=True)
class RenameCandidate:
    """A pair of symbols that likely represent a rename (same code, different name).

    Attributes:
        old_name: Symbol name in the old binary (mangled).
        new_name: Symbol name in the new binary (mangled).
        confidence: Match confidence (0.0–1.0).
            1.0 = identical size AND code hash.
            0.8 = identical size, code hash unavailable.
            0.5 = size within tolerance, code hash differs or unavailable.
        old_fingerprint: Full fingerprint from old binary.
        new_fingerprint: Full fingerprint from new binary.
    """
    old_name: str
    new_name: str
    confidence: float
    old_fingerprint: FunctionFingerprint
    new_fingerprint: FunctionFingerprint


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum symbol size (bytes) to consider for fingerprinting.
# Tiny functions (trampolines, stubs) produce too many false matches.
_MIN_SYMBOL_SIZE = 8

# Maximum relative size difference for fuzzy matching (no code hash).
_SIZE_TOLERANCE_RATIO = 0.05  # 5%

# Sections to include in BinarySummary for ABI-relevant triage.
_ABI_SECTIONS = frozenset({
    ".text", ".rodata", ".data", ".bss", ".data.rel.ro",
    ".init_array", ".fini_array", ".dynamic",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_function_fingerprints(
    binary_path: str | Path,
) -> dict[str, FunctionFingerprint]:
    """Extract function fingerprints from an ELF binary.

    Reads .dynsym for exported FUNC symbols with st_size > 0, then reads
    the corresponding code bytes from the section they reside in to compute
    a content hash.

    Returns a dict mapping symbol name → FunctionFingerprint.
    Returns an empty dict for non-ELF files or on parse errors.
    """
    try:
        with open(binary_path, "rb") as f:
            magic = f.read(4)
            if magic != b"\x7fELF":
                return {}
            f.seek(0)
            return _extract_fingerprints(f, Path(binary_path))
    except (OSError, ELFError) as exc:
        log.warning("compute_function_fingerprints: %s: %s", binary_path, exc)
        return {}


def compute_section_summary(binary_path: str | Path) -> BinarySummary:
    """Compute section-level summary for ABI-relevant ELF sections.

    Returns a BinarySummary with hashes for .text, .rodata, .data, etc.
    Useful for quick triage: if .text hash matches, code hasn't changed.
    """
    try:
        with open(binary_path, "rb") as f:
            magic = f.read(4)
            if magic != b"\x7fELF":
                return BinarySummary()
            f.seek(0)
            return _extract_section_summary(f)
    except (OSError, ELFError) as exc:
        log.warning("compute_section_summary: %s: %s", binary_path, exc)
        return BinarySummary()


def match_renamed_functions(
    old_fps: dict[str, FunctionFingerprint],
    new_fps: dict[str, FunctionFingerprint],
) -> list[RenameCandidate]:
    """Find likely renamed functions by matching fingerprints.

    Strategy:
    1. Identify symbols only in old (removed) and only in new (added).
    2. For each removed symbol, find added symbols with matching fingerprint.
    3. Exact match: same size AND same code_hash → confidence 1.0.
    4. Size-only match: same size, no code hash → confidence 0.8.
    5. Fuzzy match: size within 5%, no code hash → confidence 0.5.

    Uses a greedy 1:1 matching approach — each symbol matched at most once.
    Matches are returned sorted by confidence (highest first).
    """
    old_only = set(old_fps) - set(new_fps)
    new_only = set(new_fps) - set(old_fps)

    if not old_only or not new_only:
        return []

    # Filter out tiny symbols (stubs/trampolines produce false matches)
    old_candidates = {
        name: fp for name, fp in old_fps.items()
        if name in old_only and fp.size >= _MIN_SYMBOL_SIZE
    }
    new_candidates = {
        name: fp for name, fp in new_fps.items()
        if name in new_only and fp.size >= _MIN_SYMBOL_SIZE
    }

    if not old_candidates or not new_candidates:
        return []

    # Build index: size → list of new candidates (for fast lookup)
    new_by_size: dict[int, list[tuple[str, FunctionFingerprint]]] = {}
    for name, fp in new_candidates.items():
        new_by_size.setdefault(fp.size, []).append((name, fp))

    # Also build code_hash → list of new candidates for exact matching
    new_by_hash: dict[str, list[tuple[str, FunctionFingerprint]]] = {}
    for name, fp in new_candidates.items():
        if fp.code_hash:
            new_by_hash.setdefault(fp.code_hash, []).append((name, fp))

    candidates: list[RenameCandidate] = []
    used_new: set[str] = set()

    # Pass 1: exact matches (same size + same code hash)
    for old_name, old_fp in sorted(old_candidates.items()):
        if not old_fp.code_hash:
            continue
        for new_name, new_fp in new_by_hash.get(old_fp.code_hash, []):
            if new_name in used_new:
                continue
            if old_fp.size == new_fp.size:
                candidates.append(RenameCandidate(
                    old_name=old_name,
                    new_name=new_name,
                    confidence=1.0,
                    old_fingerprint=old_fp,
                    new_fingerprint=new_fp,
                ))
                used_new.add(new_name)
                break

    matched_old = {c.old_name for c in candidates}

    # Pass 2: size-only matches (same size, no code hash or hash mismatch)
    for old_name, old_fp in sorted(old_candidates.items()):
        if old_name in matched_old:
            continue
        exact_size_matches = [
            (n, fp) for n, fp in new_by_size.get(old_fp.size, [])
            if n not in used_new
        ]
        # Only match if there's exactly one candidate at this size
        # (ambiguous matches are not reliable)
        if len(exact_size_matches) == 1:
            new_name, new_fp = exact_size_matches[0]
            # If both have code hashes but they differ, skip
            if old_fp.code_hash and new_fp.code_hash and old_fp.code_hash != new_fp.code_hash:
                continue
            conf = 0.8 if (not old_fp.code_hash or not new_fp.code_hash) else 1.0
            candidates.append(RenameCandidate(
                old_name=old_name,
                new_name=new_name,
                confidence=conf,
                old_fingerprint=old_fp,
                new_fingerprint=new_fp,
            ))
            used_new.add(new_name)
            matched_old.add(old_name)

    # Pass 3: fuzzy size matches (within tolerance, unique match only)
    for old_name, old_fp in sorted(old_candidates.items()):
        if old_name in matched_old:
            continue
        if old_fp.size == 0:
            continue
        fuzzy_matches: list[tuple[str, FunctionFingerprint]] = []
        for new_name, new_fp in new_candidates.items():
            if new_name in used_new:
                continue
            if new_fp.size == 0:
                continue
            # If both have code hashes but they differ, skip
            if old_fp.code_hash and new_fp.code_hash and old_fp.code_hash != new_fp.code_hash:
                continue
            size_diff = abs(old_fp.size - new_fp.size) / max(old_fp.size, new_fp.size)
            if size_diff <= _SIZE_TOLERANCE_RATIO:
                fuzzy_matches.append((new_name, new_fp))
        if len(fuzzy_matches) == 1:
            new_name, new_fp = fuzzy_matches[0]
            candidates.append(RenameCandidate(
                old_name=old_name,
                new_name=new_name,
                confidence=0.5,
                old_fingerprint=old_fp,
                new_fingerprint=new_fp,
            ))
            used_new.add(new_name)
            matched_old.add(old_name)

    # Sort by confidence descending
    candidates.sort(key=lambda c: (-c.confidence, c.old_name))
    return candidates


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_fingerprints(
    f: IO[bytes], binary_path: Path,
) -> dict[str, FunctionFingerprint]:
    """Extract fingerprints from an open ELF file."""
    elf = ELFFile(f)
    result: dict[str, FunctionFingerprint] = {}

    # Find .dynsym section
    dynsym: SymbolTableSection | None = None
    for section in elf.iter_sections():
        if isinstance(section, SymbolTableSection) and section.name == ".dynsym":
            dynsym = section
            break

    if dynsym is None:
        return result

    # Pre-load section data for code hashing.
    # Map section index → (section_offset, section_size, section_data).
    section_cache: dict[int, tuple[int, int, bytes]] = {}

    for sym in dynsym.iter_symbols():
        # Only exported FUNC symbols
        if sym.entry.st_info.type != "STT_FUNC":
            continue
        if sym.entry.st_shndx in ("SHN_UNDEF", "SHN_ABS"):
            continue
        binding = sym.entry.st_info.bind
        if binding not in ("STB_GLOBAL", "STB_WEAK"):
            continue
        vis = sym.entry.st_other.visibility
        if vis in ("STV_HIDDEN", "STV_INTERNAL"):
            continue

        name = sym.name
        size = sym.entry.st_size
        shndx = sym.entry.st_shndx

        if not name or size < _MIN_SYMBOL_SIZE:
            continue

        # Compute code hash from the section data
        code_hash = _compute_code_hash(elf, sym, shndx, section_cache)

        result[name] = FunctionFingerprint(
            name=name,
            size=size,
            code_hash=code_hash,
            section_index=shndx if isinstance(shndx, int) else 0,
        )

    return result


def _compute_code_hash(
    elf: ELFFile,
    sym: object,
    shndx: int | str,
    section_cache: dict[int, tuple[int, int, bytes]],
) -> str:
    """Compute SHA-256 of the function's code bytes.

    Returns hex digest or empty string if the bytes can't be read
    (e.g., section not loaded, symbol spans outside section bounds).
    """
    if not isinstance(shndx, int):
        return ""

    try:
        if shndx not in section_cache:
            section: Section = elf.get_section(shndx)
            if section.header.sh_type == "SHT_NOBITS":
                # .bss or similar — no actual data
                return ""
            sec_data = section.data()
            section_cache[shndx] = (
                section.header.sh_addr,
                section.header.sh_size,
                sec_data,
            )

        sec_addr, sec_size, sec_data = section_cache[shndx]
        sym_addr = sym.entry.st_value
        sym_size = sym.entry.st_size

        # Calculate offset within section data
        offset = sym_addr - sec_addr
        if offset < 0 or offset + sym_size > len(sec_data):
            return ""

        code_bytes = sec_data[offset:offset + sym_size]
        return hashlib.sha256(code_bytes).hexdigest()

    except (IndexError, KeyError, ValueError, OSError) as exc:
        log.debug("_compute_code_hash: failed for symbol at shndx=%s: %s", shndx, exc)
        return ""


def _extract_section_summary(f: IO[bytes]) -> BinarySummary:
    """Extract section-level summary from an open ELF file."""
    elf = ELFFile(f)
    sections: dict[str, SectionSummary] = {}

    for section in elf.iter_sections():
        name = section.name
        if name not in _ABI_SECTIONS:
            continue
        size = section.header.sh_size
        if section.header.sh_type == "SHT_NOBITS":
            # .bss — hash is meaningless, use size only
            content_hash = hashlib.sha256(b"").hexdigest()
        else:
            try:
                content_hash = hashlib.sha256(section.data()).hexdigest()
            except (OSError, ValueError):
                continue
        sections[name] = SectionSummary(
            name=name,
            size=size,
            content_hash=content_hash,
        )

    return BinarySummary(sections=sections)
