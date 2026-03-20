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

"""Checker — diff two AbiSnapshots, classify changes, produce a verdict."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .checker_policy import (
    API_BREAK_KINDS as _API_BREAK_KINDS,
)
from .checker_policy import (
    BREAKING_KINDS as _BREAKING_KINDS,
)
from .checker_policy import (
    COMPATIBLE_KINDS as _COMPATIBLE_KINDS,
)
from .checker_policy import (
    RISK_KINDS as _RISK_KINDS,
)
from .checker_policy import (
    ChangeKind,
    Verdict,
    compute_verdict,
)
from .checker_types import (  # noqa: F401
    Change,
    DetectorSpec,
    DiffResult,
    LibraryMetadata,
)
from .detectors import DetectorResult
from .diff_filtering import (  # noqa: F401
    _ROOT_TYPE_CHANGE_KINDS,
    _compute_confidence,
    _deduplicate_ast_dwarf,
    _deduplicate_cross_detector,
    _downgrade_opaque_struct_changes,
    _downgrade_opaque_type_changes,
    _enrich_affected_symbols,
    _enrich_source_locations,
    _filter_opaque_size_changes,
    _filter_redundant,
    _filter_reserved_field_renames,
    _match_root_type,
)
from .diff_platform import (  # noqa: F401
    _diff_dwarf,
    _diff_elf,
    _diff_elf_deleted_fallback,
    _diff_elf_symbol_metadata,
    _diff_leaked_dependency_symbols,
    _diff_macho,
    _diff_pe,
    _diff_struct_layouts,
    _diff_template_inner_types,
    _extract_template_args,
    _template_outer,
)
from .diff_symbols import (
    _PUBLIC_VIS,
    _diff_access_levels,
    _diff_anon_fields,
    _diff_constants,
    _diff_functions,
    _diff_param_defaults,
    _diff_param_renames,
    _diff_param_restrict,
    _diff_param_va_list,
    _diff_pointer_levels,
    _diff_symbol_renames,
    _diff_var_access,
    _diff_variables,
)
from .diff_types import (  # noqa: F401
    _diff_const_overloads,
    _diff_enum_renames,
    _diff_enums,
    _diff_field_qualifiers,
    _diff_field_renames,
    _diff_method_qualifiers,
    _diff_reserved_fields,
    _diff_type_kind_changes,
    _diff_typedefs,
    _diff_types,
    _diff_unions,
    _diff_var_values,
    _is_version_stamped_typedef,
)
from .dwarf_advanced import (
    diff_advanced_dwarf,  # noqa: F401 — re-export for monkeypatching
)
from .model import AbiSnapshot
from .policy_file import PolicyFile

if TYPE_CHECKING:
    from .suppression import SuppressionList

__all__ = [
    "ChangeKind",
    "Verdict",
    "_BREAKING_KINDS",
    "_COMPATIBLE_KINDS",
    "_API_BREAK_KINDS",
    "_RISK_KINDS",
    "_SOURCE_BREAK_KINDS",  # deprecated alias
    "Change",
    "LibraryMetadata",
    "DiffResult",
    "compare",
    "_ROOT_TYPE_CHANGE_KINDS",
]

# Deprecated alias — kept for external consumers; will be removed in v2.0
_SOURCE_BREAK_KINDS = _API_BREAK_KINDS


# _DetectorSpec is now DetectorSpec in checker_types; keep alias for internal use.
_DetectorSpec = DetectorSpec


def _diff_advanced_dwarf(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Sprint 4: calling convention, packing, toolchain flag drift.

    Kept in checker.py (not diff_platform) so that tests can monkeypatch
    ``checker_mod.diff_advanced_dwarf`` and have the patch take effect.
    """
    from .dwarf_advanced import AdvancedDwarfMetadata

    o: AdvancedDwarfMetadata = getattr(old, "dwarf_advanced", None) or AdvancedDwarfMetadata()
    n: AdvancedDwarfMetadata = getattr(new, "dwarf_advanced", None) or AdvancedDwarfMetadata()

    _kind_map = {
        "calling_convention_changed": ChangeKind.CALLING_CONVENTION_CHANGED,
        "value_abi_trait_changed": ChangeKind.VALUE_ABI_TRAIT_CHANGED,
        "struct_packing_changed": ChangeKind.STRUCT_PACKING_CHANGED,
        "toolchain_flag_drift": ChangeKind.TOOLCHAIN_FLAG_DRIFT,
        "type_visibility_changed": ChangeKind.TYPE_VISIBILITY_CHANGED,
        "frame_register_changed": ChangeKind.FRAME_REGISTER_CHANGED,
    }

    return [
        Change(
            kind=_kind_map[kind_str],
            symbol=sym,
            description=desc,
            old_value=old_val,
            new_value=new_val,
        )
        for kind_str, sym, desc, old_val, new_val in diff_advanced_dwarf(o, n)
        if kind_str in _kind_map
    ]


def compare(
    old: AbiSnapshot,
    new: AbiSnapshot,
    suppression: SuppressionList | None = None,
    *,
    policy: str = "strict_abi",
    policy_file: PolicyFile | None = None,
) -> DiffResult:
    """Diff two AbiSnapshots and return a DiffResult with verdict.

    Args:
        old: Old ABI snapshot.
        new: New ABI snapshot.
        suppression: Optional suppression list to filter known changes.
        policy: Policy profile name to use for verdict classification.
            Available: "strict_abi" (default), "sdk_vendor", "plugin_abi".
            Ignored when *policy_file* is provided.
        policy_file: Optional :class:`~abicheck.policy_file.PolicyFile` instance
            for user-defined per-kind verdict overrides.  When provided,
            *policy* is used only as the ``base_policy`` fallback inside the
            file (i.e. the file's own ``base_policy`` field takes precedence).
    """

    detector_fns: list[_DetectorSpec] = [
        _DetectorSpec("functions", _diff_functions),
        _DetectorSpec("variables", _diff_variables),
        _DetectorSpec("types", _diff_types),
        _DetectorSpec("enums", _diff_enums),
        _DetectorSpec("method_qualifiers", _diff_method_qualifiers),
        _DetectorSpec("unions", _diff_unions),
        _DetectorSpec("typedefs", _diff_typedefs),
        _DetectorSpec("elf", _diff_elf),
        _DetectorSpec(
            "pe",
            _diff_pe,
            lambda o, n: (
                o.pe is not None and n.pe is not None,
                "missing PE metadata",
            ),
        ),
        _DetectorSpec(
            "macho",
            _diff_macho,
            lambda o, n: (
                o.macho is not None and n.macho is not None,
                "missing Mach-O metadata",
            ),
        ),
        _DetectorSpec("dwarf", _diff_dwarf),
        _DetectorSpec(
            "advanced_dwarf",
            _diff_advanced_dwarf,
            lambda o, n: ((o.dwarf_advanced is not None and n.dwarf_advanced is not None), "missing DWARF advanced metadata"),
        ),
        _DetectorSpec("enum_renames", _diff_enum_renames),
        _DetectorSpec("field_qualifiers", _diff_field_qualifiers),
        _DetectorSpec("field_renames", _diff_field_renames),
        _DetectorSpec("param_defaults", _diff_param_defaults),
        _DetectorSpec("param_renames", _diff_param_renames),
        _DetectorSpec("pointer_levels", _diff_pointer_levels),
        _DetectorSpec("access_levels", _diff_access_levels),
        _DetectorSpec("anon_fields", _diff_anon_fields),
        _DetectorSpec("var_values", _diff_var_values),
        _DetectorSpec("type_kind_changes", _diff_type_kind_changes),
        _DetectorSpec("reserved_fields", _diff_reserved_fields),
        _DetectorSpec("const_overloads", _diff_const_overloads),
        _DetectorSpec("param_restrict", _diff_param_restrict),
        _DetectorSpec("param_va_list", _diff_param_va_list),
        _DetectorSpec("constants", _diff_constants),
        _DetectorSpec("var_access", _diff_var_access),
        _DetectorSpec("elf_deleted_fallback", _diff_elf_deleted_fallback),
        _DetectorSpec("template_inner_types", _diff_template_inner_types),
        _DetectorSpec("symbol_renames", _diff_symbol_renames),
    ]

    changes: list[Change] = []
    detector_results: list[DetectorResult] = []
    for spec in detector_fns:
        enabled, reason = spec.support(old, new)
        if not enabled:
            detector_results.append(
                DetectorResult(name=spec.name, changes_count=0, enabled=False, coverage_gap=reason)
            )
            continue

        detected = spec.run(old, new)
        changes.extend(detected)
        detector_results.append(DetectorResult(name=spec.name, changes_count=len(detected), enabled=True))

    # Suppress TYPE_FIELD_REMOVED false positives caused by reserved-field renames.
    # Must run before AST/DWARF dedup so that DWARF duplicates of the suppressed
    # findings are also removed.
    changes = _filter_reserved_field_renames(changes)

    # Suppress size-only growth for opaque pointer-handle types (case62).
    # Filtered-out changes are collected for the redundant list so they appear
    # in the audit trail (report JSON) rather than being silently discarded.
    changes, opaque_filtered = _filter_opaque_size_changes(changes, old, new)

    # Downgrade opaque struct changes: if a type is opaque (forward-decl only)
    # in BOTH old and new snapshots, size/field changes from DWARF are invisible
    # to consumers who only use pointer-to-type.  This complements the filter
    # above for cases where AST never sees the struct definition (pure opaque).
    changes = _downgrade_opaque_struct_changes(changes, old, new)

    # Deduplicate AST/DWARF before suppression so a single canonical change
    # remains for suppression matching (avoids suppressed AST entry leaving
    # an unsuppressed DWARF duplicate).
    changes = _deduplicate_ast_dwarf(changes)

    # Cross-detector dedup: collapse overlapping reports from different
    # detectors (e.g., function detector + PE/Mach-O detector both emitting
    # FUNC_REMOVED for the same symbol).
    changes = _deduplicate_cross_detector(changes)

    # Suppress structural changes for opaque types (forward-declared only
    # in the public header, is_opaque=True).  Consumers never see the layout.
    changes = _downgrade_opaque_type_changes(changes, old, new)

    # Enrich source locations before suppression so source_location-based
    # suppression rules can match (most changes have source_location=None
    # until enrichment runs).
    _enrich_source_locations(changes, old, new)

    suppressed: list[Change] = []
    if suppression is not None:
        filtered: list[Change] = []
        for c in changes:
            if suppression.is_suppressed(c):
                suppressed.append(c)
            else:
                filtered.append(c)
        changes = filtered

    # Redundancy filtering: split unsuppressed changes into kept + redundant.
    # Applied after suppression so suppressed changes never contribute to the
    # verdict. Verdict is computed on kept + redundant (all unsuppressed).
    kept, redundant = _filter_redundant(changes)

    # Opaque-handle size-change findings are moved to the redundant list so
    # they appear in the report's audit trail without affecting the verdict.
    redundant.extend(opaque_filtered)

    # Post-processing: enrich remaining changes with affected symbols
    _enrich_affected_symbols(kept, old)

    # Verdict computed on all unsuppressed changes (kept + redundant)
    all_unsuppressed = kept + redundant
    verdict = policy_file.compute_verdict(all_unsuppressed) if policy_file is not None else compute_verdict(all_unsuppressed, policy=policy)
    effective_policy = policy_file.base_policy if policy_file is not None else policy

    # Compute old_symbol_count once for downstream metrics (Bug 8)
    old_sym_count = sum(
        1 for f in old.functions if f.visibility in _PUBLIC_VIS
    ) + sum(
        1 for v in old.variables if v.visibility in _PUBLIC_VIS
    )

    # Compute evidence tiers and confidence from detector results.
    evidence_tiers, confidence, coverage_warnings = _compute_confidence(
        detector_results, old, new,
    )

    return DiffResult(
        old_version=old.version,
        new_version=new.version,
        library=old.library,
        changes=kept,
        verdict=verdict,
        suppressed_count=len(suppressed),
        suppressed_changes=suppressed,
        suppression_file_provided=suppression is not None,
        detector_results=detector_results,
        policy=effective_policy,
        policy_file=policy_file,
        redundant_changes=redundant,
        redundant_count=len(redundant),
        old_symbol_count=old_sym_count if old_sym_count > 0 else None,
        confidence=confidence,
        evidence_tiers=evidence_tiers,
        coverage_warnings=coverage_warnings,
    )
