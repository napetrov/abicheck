"""core/pipeline.py — Phase 1c+2 end-to-end adapter.

Wires the v0.2 components into a single callable:

    AbiSnapshot
        → Normalizer → NormalizedSnapshot
        → diff_symbols + diff_type_layout_diffs → list[Change]
        → SuppressionEngine → SuppressionResult
        → PolicyProfile → PolicyResult

Pipeline (Phase 2)::

    extract → normalize → diff → suppress → policy → PolicyResult

Note: importing abicheck.core.pipeline does NOT import re2 / suppressions.
      re2 is loaded lazily inside analyse_full() only.
"""
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from abicheck.core.corpus.normalizer import Normalizer
from abicheck.core.diff.symbol_diff import diff_symbols
from abicheck.core.diff.type_layout_diff import diff_type_layouts
from abicheck.core.model import Change, PolicyResult
from abicheck.model import AbiSnapshot

if TYPE_CHECKING:
    from abicheck.core.suppressions import SuppressionEngine, SuppressionRule

_normalizer = Normalizer()


def analyse(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Run the v0.2 diff pipeline on two AbiSnapshots.

    Returns raw Changes (no suppression, no policy verdict), sorted
    deterministically by (entity_type, entity_name, change_kind).
    """
    if old is None or new is None:
        raise TypeError("AbiSnapshot cannot be None")
    norm_old = _normalizer.normalize(old)
    norm_new = _normalizer.normalize(new)

    changes: list[Change] = []
    changes.extend(diff_symbols(norm_old, norm_new))
    changes.extend(diff_type_layouts(norm_old, norm_new))

    return sorted(changes, key=lambda c: (c.entity_type, c.entity_name, c.change_kind.value))


def analyse_full(
    old: AbiSnapshot,
    new: AbiSnapshot,
    *,
    rules: list[SuppressionRule] | None = None,
    policy: str = "strict_abi",
    engine: SuppressionEngine | None = None,
) -> PolicyResult:
    """Run the full v0.2 pipeline: diff → suppress → policy → PolicyResult."""
    from abicheck.core.policy import get_profile  # noqa: PLC0415
    from abicheck.core.suppressions import SuppressionEngine as _Engine  # noqa: PLC0415

    changes = analyse(old, new)

    if engine is None:
        engine = _Engine(rules or [])
    elif rules:
        warnings.warn(
            "Both 'engine' and 'rules' provided to analyse_full(); "
            "'rules' will be ignored in favor of the pre-built engine.",
            stacklevel=2,
        )

    sup_result = engine.apply(changes)

    all_changes = sorted(
        sup_result.active + sup_result.suppressed,
        key=lambda c: (c.entity_type, c.entity_name, c.change_kind.value),
    )

    profile = get_profile(policy)
    return profile.apply(all_changes)
