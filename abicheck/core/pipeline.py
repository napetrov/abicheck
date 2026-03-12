"""core/pipeline.py — Phase 1c+2 end-to-end adapter.

Wires the v0.2 components into a single callable:

    AbiSnapshot
        → Normalizer → NormalizedSnapshot
        → diff_symbols + diff_type_layouts → list[Change]
        → SuppressionEngine → SuppressionResult
        → PolicyProfile → PolicyResult

Usage::

    from abicheck.core.pipeline import analyse, analyse_full
    from abicheck.dumper import dump

    snap_old = dump(so_old, [header_old])
    snap_new = dump(so_new, [header_new])

    # Simple: just get raw Changes
    changes = analyse(snap_old, snap_new)

    # Full: suppression + policy verdict
    from abicheck.core.suppressions import SuppressionRule
    rules = [SuppressionRule(entity_glob="__internal_*", reason="internal symbols")]
    result = analyse_full(snap_old, snap_new, rules=rules, policy="strict_abi")
    print(result.summary.verdict)

Pipeline (Phase 2)::

    extract → normalize → diff → suppress → policy → PolicyResult

TODO Phase 3: add per-profile normalizer config
TODO Phase 3: multiprocessing.Pool.map over per-binary extraction
"""
from __future__ import annotations

from abicheck.core.corpus.normalizer import Normalizer
from abicheck.core.diff.symbol_diff import diff_symbols
from abicheck.core.diff.type_layout_diff import diff_type_layouts
from abicheck.core.model import Change, PolicyResult
from abicheck.core.policy import get_profile
from abicheck.core.suppressions import SuppressionEngine, SuppressionRule
from abicheck.model import AbiSnapshot

# Module-level singleton — stateless, safe for repeated calls.
# TODO Phase 3: replace with per-profile Normalizer configuration
_normalizer = Normalizer()


def analyse(
    old: AbiSnapshot,
    new: AbiSnapshot,
) -> list[Change]:
    """Run the v0.2 diff pipeline on two AbiSnapshots.

    Returns raw Changes (no suppression, no policy verdict).
    Sorted deterministically by (entity_type, entity_name, change_kind).
    """
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
    """Run the full v0.2 pipeline: diff → suppress → policy → PolicyResult.

    Args:
        old:    AbiSnapshot of the before version
        new:    AbiSnapshot of the after version
        rules:  suppression rules (empty = no suppression); ignored when engine is provided
        policy: policy profile name ("strict_abi" | "sdk_vendor" | "plugin_abi")
        engine: pre-built SuppressionEngine (pass this for batch callers to avoid
                re-compiling RE2 patterns on every call)

    Returns:
        PolicyResult with per-change AnnotatedChange list and aggregate summary.
    """
    changes = analyse(old, new)

    # Suppression pass — pre-built engine takes precedence over rules
    if engine is None:
        engine = SuppressionEngine(rules or [])
    sup_result = engine.apply(changes)

    # Merge active + suppressed; restore original sort order
    all_changes = sorted(
        sup_result.active + sup_result.suppressed,
        key=lambda c: (c.entity_type, c.entity_name, c.change_kind.value),
    )

    # Policy verdict — suppressed changes have severity=SUPPRESSED, handled by apply()
    profile = get_profile(policy)
    return profile.apply(all_changes)
