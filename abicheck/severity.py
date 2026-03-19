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

"""Severity configuration for issue categories.

Builds on top of the existing policy/verdict system in ``checker_policy``
to provide user-facing severity presets that control exit codes and report
presentation.

The canonical kind-set classification lives in ``checker_policy`` (single
source of truth).  This module provides:

- **SeverityLevel** — ``error`` / ``warning`` / ``info``.
- **IssueCategory** — the four high-level categories users interact with.
- **SeverityConfig** — maps each category to a severity level.
- **Presets** — ``default``, ``strict``, ``info-only``.
- **classify_change** / **categorize_changes** — thin wrappers over the
  canonical kind sets.
- **compute_exit_code** — severity-aware exit-code computation.

The four categories map to the canonical kind sets as follows:

1. **abi_breaking** → ``BREAKING_KINDS`` — clear ABI/API incompatibilities.
   Default: ``error``.
2. **potential_breaking** → ``API_BREAK_KINDS ∪ RISK_KINDS`` — potential
   incompatibilities that need manual review.  Default: ``warning``.
3. **quality_issues** → ``QUALITY_KINDS`` (= ``COMPATIBLE_KINDS − ADDITION_KINDS``)
   — problematic behaviors such as exposing std symbols, missing SONAME,
   toolchain flag drift.  Default: ``warning``.
4. **additions** → ``ADDITION_KINDS`` — new public symbols, types, enum
   members.  Default: ``info``.

Each category can be set to ``error``, ``warning``, or ``info``:

- ``error`` — flagged prominently in the report, contributes to non-zero exit code.
- ``warning`` — shown as a warning in the report, does NOT affect exit code.
- ``info`` — informational only, shown in the report but neutral.

Built-in presets:

- ``default`` — abi_breaking=error, potential_breaking=warning,
  quality_issues=warning, additions=info.
- ``strict`` — all categories set to error.
- ``info-only`` — all categories set to info (purely informational report).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from .checker_policy import (
    ADDITION_KINDS,
    API_BREAK_KINDS,
    BREAKING_KINDS,
    QUALITY_KINDS,
    RISK_KINDS,
    ChangeKind,
    HasKind,
)


class SeverityLevel(str, Enum):
    """Criticality level for an issue category."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueCategory(str, Enum):
    """The four high-level issue categories."""

    ABI_BREAKING = "abi_breaking"
    POTENTIAL_BREAKING = "potential_breaking"
    QUALITY_ISSUES = "quality_issues"
    ADDITIONS = "additions"


# ---------------------------------------------------------------------------
# Change-kind -> IssueCategory classification
# ---------------------------------------------------------------------------
# Delegates entirely to the canonical kind sets in checker_policy.py.
# No duplicate frozensets here — single source of truth.


def classify_change(kind: ChangeKind) -> IssueCategory:
    """Classify a ChangeKind into one of the four issue categories.

    Uses the canonical kind sets from ``checker_policy`` directly.
    Unknown kinds default to ``ABI_BREAKING`` (fail-safe).
    """
    if kind in BREAKING_KINDS:
        return IssueCategory.ABI_BREAKING
    if kind in API_BREAK_KINDS or kind in RISK_KINDS:
        return IssueCategory.POTENTIAL_BREAKING
    if kind in ADDITION_KINDS:
        return IssueCategory.ADDITIONS
    if kind in QUALITY_KINDS:
        return IssueCategory.QUALITY_ISSUES
    # Fail-safe: unclassified kinds are treated as breaking.
    return IssueCategory.ABI_BREAKING


# ---------------------------------------------------------------------------
# Severity configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeverityConfig:
    """Maps each issue category to a criticality level.

    Attributes:
        abi_breaking: Severity for clear ABI/API incompatibilities.
        potential_breaking: Severity for potential incompatibilities needing review.
        quality_issues: Severity for problematic behaviors (e.g., std symbol leaks).
        additions: Severity for additive changes (new public API surface).
    """

    abi_breaking: SeverityLevel = SeverityLevel.ERROR
    potential_breaking: SeverityLevel = SeverityLevel.WARNING
    quality_issues: SeverityLevel = SeverityLevel.WARNING
    additions: SeverityLevel = SeverityLevel.INFO

    def level_for(self, category: IssueCategory) -> SeverityLevel:
        """Return the configured severity level for *category*.

        Works because SeverityConfig field names match IssueCategory values.
        """
        result: SeverityLevel = getattr(self, category.value)
        return result

    def level_for_kind(self, kind: ChangeKind) -> SeverityLevel:
        """Return the configured severity level for a specific ChangeKind."""
        return self.level_for(classify_change(kind))

    def has_errors(self, changes: Sequence[HasKind]) -> bool:
        """Return True if any change falls into a category configured as error."""
        return any(
            self.level_for_kind(c.kind) == SeverityLevel.ERROR for c in changes
        )

    def describe(self) -> str:
        """Human-readable summary of this configuration."""
        lines = []
        for cat in IssueCategory:
            lines.append(f"  {cat.value}: {self.level_for(cat).value}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Built-in presets
# ---------------------------------------------------------------------------

#: Default preset: breaks are errors, potential issues and quality are warnings,
#: additions are informational.
PRESET_DEFAULT = SeverityConfig()

#: Strict preset: everything is an error.
PRESET_STRICT = SeverityConfig(
    abi_breaking=SeverityLevel.ERROR,
    potential_breaking=SeverityLevel.ERROR,
    quality_issues=SeverityLevel.ERROR,
    additions=SeverityLevel.ERROR,
)

#: Info-only preset: everything is informational (no exit-code impact).
PRESET_INFO_ONLY = SeverityConfig(
    abi_breaking=SeverityLevel.INFO,
    potential_breaking=SeverityLevel.INFO,
    quality_issues=SeverityLevel.INFO,
    additions=SeverityLevel.INFO,
)

SEVERITY_PRESETS: dict[str, SeverityConfig] = {
    "default": PRESET_DEFAULT,
    "strict": PRESET_STRICT,
    "info-only": PRESET_INFO_ONLY,
}


def resolve_severity_config(
    preset: str | None = None,
    *,
    abi_breaking: str | None = None,
    potential_breaking: str | None = None,
    quality_issues: str | None = None,
    additions: str | None = None,
) -> SeverityConfig:
    """Build a SeverityConfig from a preset name and optional per-category overrides.

    Per-category overrides take precedence over the preset.

    Args:
        preset: One of ``default``, ``strict``, ``info-only``, or *None* for default.
        abi_breaking: Override for the abi_breaking category (``error``, ``warning``, ``info``).
        potential_breaking: Override for potential_breaking.
        quality_issues: Override for quality_issues.
        additions: Override for additions.

    Returns:
        A fully resolved SeverityConfig.

    Raises:
        ValueError: If the preset name or any override value is invalid.
    """
    if preset is None:
        base = PRESET_DEFAULT
    else:
        looked_up = SEVERITY_PRESETS.get(preset)
        if looked_up is None:
            raise ValueError(
                f"Unknown severity preset {preset!r}. "
                f"Valid presets: {sorted(SEVERITY_PRESETS)}"
            )
        base = looked_up

    def _parse(name: str, raw: str | None, fallback: SeverityLevel) -> SeverityLevel:
        if raw is None:
            return fallback
        try:
            return SeverityLevel(raw.lower())
        except ValueError:
            raise ValueError(
                f"Invalid severity level {raw!r} for {name}. "
                f"Valid values: error, warning, info"
            ) from None

    return SeverityConfig(
        abi_breaking=_parse("abi_breaking", abi_breaking, base.abi_breaking),
        potential_breaking=_parse(
            "potential_breaking", potential_breaking, base.potential_breaking
        ),
        quality_issues=_parse("quality_issues", quality_issues, base.quality_issues),
        additions=_parse("additions", additions, base.additions),
    )


# ---------------------------------------------------------------------------
# Exit code computation
# ---------------------------------------------------------------------------

# Severity-aware exit codes:
#   0 — no error-level findings
#   1 — error-level findings in additions or quality_issues only
#   2 — error-level findings in potential_breaking (but not abi_breaking)
#   4 — error-level findings in abi_breaking

_CATEGORY_EXIT_CODES: dict[IssueCategory, int] = {
    IssueCategory.ABI_BREAKING: 4,
    IssueCategory.POTENTIAL_BREAKING: 2,
    IssueCategory.QUALITY_ISSUES: 1,
    IssueCategory.ADDITIONS: 1,
}


def compute_exit_code(
    changes: Sequence[HasKind],
    config: SeverityConfig,
) -> int:
    """Compute the process exit code based on severity configuration.

    Returns the highest exit code among categories that have both:
    - at least one finding, AND
    - severity configured as ``error``.

    Returns 0 if no category at error level has findings.
    """
    worst = 0
    for change in changes:
        cat = classify_change(change.kind)
        if config.level_for(cat) == SeverityLevel.ERROR:
            code = _CATEGORY_EXIT_CODES[cat]
            if code > worst:
                worst = code
    return worst


@dataclass(frozen=True)
class CategorizedChanges:
    """Changes partitioned into the four issue categories."""

    abi_breaking: list[HasKind]
    potential_breaking: list[HasKind]
    quality_issues: list[HasKind]
    additions: list[HasKind]


def categorize_changes(changes: Sequence[HasKind]) -> CategorizedChanges:
    """Partition changes into the four issue categories."""
    abi: list[HasKind] = []
    potential: list[HasKind] = []
    quality: list[HasKind] = []
    adds: list[HasKind] = []

    for c in changes:
        cat = classify_change(c.kind)
        if cat == IssueCategory.ABI_BREAKING:
            abi.append(c)
        elif cat == IssueCategory.POTENTIAL_BREAKING:
            potential.append(c)
        elif cat == IssueCategory.QUALITY_ISSUES:
            quality.append(c)
        else:
            adds.append(c)

    return CategorizedChanges(
        abi_breaking=abi,
        potential_breaking=potential,
        quality_issues=quality,
        additions=adds,
    )
