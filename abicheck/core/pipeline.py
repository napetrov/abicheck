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
from typing import TYPE_CHECKING, Literal

from abicheck.core.corpus.normalizer import Normalizer
from abicheck.core.diff.symbol_diff import diff_symbols
from abicheck.core.diff.type_layout_diff import diff_type_layouts
from abicheck.core.errors import ValidationError
from abicheck.core.model import Change, PolicyResult
from abicheck.model import AbiSnapshot

if TYPE_CHECKING:
    from abicheck.core.suppressions import SuppressionEngine, SuppressionRule

_normalizer = Normalizer()

# Valid platform values for scope.platform filtering (Phase 3).
KNOWN_PLATFORMS: frozenset[str] = frozenset({"elf", "pe", "macho"})

# Valid profile values for scope.profile filtering (Phase 4).
KNOWN_PROFILES: frozenset[str] = frozenset({"c", "cpp", "sycl"})


def detect_platform(snapshot: AbiSnapshot) -> Literal["elf", "pe", "macho"] | None:
    """Detect the binary format platform from an AbiSnapshot.

    Detection priority:
    1. snapshot.platform if already set (explicit override by caller/dumper)
    2. snapshot.elf is not None → "elf"
    3. None (unknown — PE/MachO not yet implemented)

    Returns the detected platform string or None if unknown.
    """
    if snapshot.platform is not None:
        p = snapshot.platform
        if p in KNOWN_PLATFORMS:
            return p  # type: ignore[return-value]
        return None
    if snapshot.elf is not None:
        return "elf"
    return None


def detect_profile(snapshot: AbiSnapshot) -> Literal["c", "cpp", "sycl"] | None:
    """Detect the language profile from an AbiSnapshot.

    Detection priority:
    1. snapshot.language_profile if already set (explicit override by caller/dumper)
    2. Heuristic from function symbols:
       - Any function has C++ mangling (_Z prefix) → "cpp"
       - All public functions are extern "C" (is_extern_c=True) → "c"
       - ELF-only mode with no _Z prefix among any public function → "c"
         (absence of Itanium ABI mangling strongly implies C linkage)
    3. None (unknown — mixed or no functions)

    Note: "sycl" cannot be auto-detected from the model; set snapshot.language_profile
    explicitly when processing SYCL libraries.
    """
    if snapshot.language_profile is not None:
        p = snapshot.language_profile
        if p in KNOWN_PROFILES:
            return p  # type: ignore[return-value]
        return None

    public_funcs = [
        f for f in snapshot.functions
        if f.visibility.value in ("public", "elf_only")
    ]
    if not public_funcs:
        return None

    # If any function has C++ mangling → cpp
    if any(f.mangled.startswith("_Z") for f in public_funcs):
        return "cpp"

    # If all public functions are explicitly extern "C" → c
    if all(f.is_extern_c for f in public_funcs):
        return "c"

    # ELF-only mode: no _Z prefix among any symbol → strong signal of C linkage
    # (Itanium ABI _Z prefix is unambiguous; absence implies C linkage)
    if getattr(snapshot, "elf_only_mode", False):
        return "c"

    return None


def analyse(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Run the v0.2 diff pipeline on two AbiSnapshots.

    Returns raw Changes (no suppression, no policy verdict), sorted
    deterministically by (entity_type, entity_name, change_kind).
    """
    if old is None:
        raise ValidationError("old AbiSnapshot is None")
    if new is None:
        raise ValidationError("new AbiSnapshot is None")
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

    Platform and language profile are auto-detected from the snapshots (new first,
    old as fallback) and passed to the suppression engine for scope filtering (Phase 3/4).
    When context cannot be detected, conservative skip semantics apply — suppression
    rules with scope filters still match (safest default).
    """
    from abicheck.core.policy import get_profile  # noqa: PLC0415
    from abicheck.core.suppressions import SuppressionEngine as _Engine  # noqa: PLC0415

    changes = analyse(old, new)

    # Phase 3: auto-detect platform from snapshot for suppression scope filtering.
    platform_ctx = detect_platform(new) or detect_platform(old)

    # Phase 4: auto-detect language profile from snapshot.
    profile_ctx = detect_profile(new) or detect_profile(old)

    if engine is None:
        engine = _Engine(rules or [])
    elif rules:
        warnings.warn(
            "Both 'engine' and 'rules' provided to analyse_full(); "
            "'rules' will be ignored in favor of the pre-built engine.",
            stacklevel=2,
        )

    sup_result = engine.apply(changes, platform_context=platform_ctx, profile_context=profile_ctx)

    all_changes = sorted(
        sup_result.active + sup_result.suppressed,
        key=lambda c: (c.entity_type, c.entity_name, c.change_kind.value),
    )

    policy_profile = get_profile(policy)
    return policy_profile.apply(all_changes)
