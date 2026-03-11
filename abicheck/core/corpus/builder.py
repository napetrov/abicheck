"""CorpusBuilder — Phase 1b.

Builds a normalized corpus representation from NormalizedSnapshot.

Design goals:
- Integer-keyed type map (`reachable_types`) for fast diff lookups
- O(1) indexes for symbols and source exports
- Deterministic IDs for reproducibility (sorted insertion order)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from abicheck.model import Function, RecordType, Variable, Visibility

from .normalizer import NormalizedSnapshot


@dataclass(slots=True)
class Corpus:
    """Normalized ABI/API representation (Phase 1b scaffold)."""
    public_interfaces: dict[str, Function] = field(default_factory=dict)
    source_exports: dict[str, Function] = field(default_factory=dict)
    reachable_types: dict[int, RecordType] = field(default_factory=dict)  # int-keyed by design
    binary_exports: dict[int, str] = field(default_factory=dict)           # id -> mangled symbol
    dependency_closure: dict[str, list[str]] = field(default_factory=dict) # DAG scaffold

    corpus_version: str | None = None
    schema_version: str = "0.2"


class CorpusBuilder:
    """Builds Corpus from a NormalizedSnapshot."""

    def build(self, normalized: NormalizedSnapshot) -> Corpus:
        # Public source interfaces: public functions by mangled name
        public_funcs = {
            f.mangled: f
            for f in normalized.functions
            if f.visibility == Visibility.PUBLIC
        }

        # Integer-keyed binary export map (deterministic ordering)
        ordered_symbols = sorted(public_funcs.keys())
        binary_exports = {idx: mangled for idx, mangled in enumerate(ordered_symbols)}

        # Integer-keyed type map (deterministic ordering by type name)
        ordered_types = sorted(normalized.types, key=lambda t: t.name)
        reachable_types = {idx: t for idx, t in enumerate(ordered_types)}

        # Source exports initially mirror public interfaces (to be refined in Phase 2+)
        source_exports = dict(public_funcs)

        return Corpus(
            public_interfaces=public_funcs,
            source_exports=source_exports,
            reachable_types=reachable_types,
            binary_exports=binary_exports,
            dependency_closure={},
            corpus_version=normalized.version,
            schema_version="0.2",
        )
