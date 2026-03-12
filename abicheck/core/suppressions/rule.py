"""SuppressionRule — v0.2 data model.

A suppression rule declares that a matching Change should be treated as
SUPPRESSED rather than BREAK/REVIEW_NEEDED.

Design:
- entity_glob  (preferred): shell-style glob, friendlier to write in config files
- entity_regex (escape hatch): RE2 regex for complex patterns
- scope:       platform/profile/version_range filtering
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class VersionRange:
    """Inclusive version range for suppression scope.

    scheme:
      "semver"           — semver ordering (1.2.3)
      "intel_quarterly"  — Intel quarterly notation (2024.1, 2024.2)
      "linear"           — simple string/numeric ordering
    """
    from_version: str | None = None   # None = -inf
    to_version: str | None = None     # None = +inf
    inclusive: bool = True
    scheme: Literal["semver", "intel_quarterly", "linear"] = "semver"


@dataclass(slots=True)
class SuppressionScope:
    """Optional filters controlling where a suppression rule applies."""
    platform: str | None = None       # "elf" | "pe" | "macho" | None=any
    profile: str | None = None        # "c" | "cpp" | "sycl" | None=any
    version_range: VersionRange | None = None  # None=all versions


@dataclass(slots=True)
class SuppressionRule:
    """A single suppression rule.

    Matching precedence:
      1. entity_glob match (if provided) — shell-style glob
      2. entity_regex match (if provided) — RE2 regex
      3. change_kind match (always required unless None)

    If both entity_glob and entity_regex are provided, BOTH must match.
    If neither is provided, the rule matches any entity name.

    scope filters are applied before entity matching.
    """
    change_kind: str | None = None     # ChangeKind.value string, or None=any
    entity_glob: str | None = None     # "std::*" — glob preferred
    entity_regex: str | None = None    # "^std::.*$" — RE2 escape hatch
    reason: str = ""                   # audit trail
    scope: SuppressionScope = field(default_factory=SuppressionScope)
