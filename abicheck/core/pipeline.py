"""core/pipeline.py — Phase 1c end-to-end adapter.

Wires the v0.2 components (Normalizer → diff engines) into a single
callable that accepts two AbiSnapshot objects and returns a list of
v0.2 Change objects.

This is the integration layer — it does NOT replace the existing
``abicheck.checker.compare()``. Both coexist until Phase 2+ migration.

Usage::

    from abicheck.core.pipeline import analyse
    from abicheck.dumper import dump

    snap_old = dump(so_old, [header_old])
    snap_new = dump(so_new, [header_new])
    changes = analyse(snap_old, snap_new)

Pipeline::

    AbiSnapshot
        → Normalizer → NormalizedSnapshot
        → diff_symbols + diff_type_layouts
        → list[Change]
"""
from __future__ import annotations

from abicheck.core.corpus.normalizer import Normalizer
from abicheck.core.diff.symbol_diff import diff_symbols
from abicheck.core.diff.type_layout_diff import diff_type_layouts
from abicheck.core.model import Change
from abicheck.model import AbiSnapshot

_normalizer = Normalizer()


def analyse(
    old: AbiSnapshot,
    new: AbiSnapshot,
) -> list[Change]:
    """Run the v0.2 pipeline on two AbiSnapshots.

    Returns a deduplicated list of Change objects sorted by entity_name.
    """
    norm_old = _normalizer.normalize(old)
    norm_new = _normalizer.normalize(new)

    changes: list[Change] = []
    changes.extend(diff_symbols(norm_old, norm_new))
    changes.extend(diff_type_layouts(norm_old, norm_new))

    # Deterministic output order
    return sorted(changes, key=lambda c: (c.entity_type, c.entity_name, c.change_kind.value))
