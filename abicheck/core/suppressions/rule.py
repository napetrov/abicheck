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

    Note: `inclusive=True` covers [from, to] (fully closed range).
    TODO Phase 2b: add from_inclusive/to_inclusive split to support half-open
    ranges like [1.2.0, 2.0.0) which are common in semver policies.
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
      1. namespace_pattern match (if provided) — RE2 regex on the namespace
         prefix of the entity name (everything before the last '::')
      2. entity_glob match (if provided) — shell-style glob on full entity name
      3. entity_regex match (if provided) — RE2 regex on full entity name
      4. change_kind match (always required unless None)

    If multiple patterns are provided, ALL must match.
    If neither entity_glob, entity_regex, nor namespace_pattern is provided,
    the rule matches any entity name.

    namespace_pattern usage:
      - Matches the namespace prefix of the entity name (text before last '::')
      - e.g. namespace_pattern="internal" matches "internal::Foo" and "internal::bar"
        but NOT "internal::detail::Foo" (only the immediate parent namespace is checked)
      - To match all depths: namespace_pattern=r"internal(::.*)?"
      - namespace_pattern="std" matches "std::string" but not "mystd::string"
      - Uses RE2 fullmatch on the namespace prefix for safety

    scope filters are applied before entity matching.
    """
    change_kind: str | None = None         # ChangeKind.value string, or None=any
    entity_glob: str | None = None         # "std::*" — glob preferred
    entity_regex: str | None = None        # "^std::.*$" — RE2 escape hatch
    reason: str = ""                       # audit trail
    namespace_pattern: str | None = None   # RE2 pattern matched against namespace prefix
    scope: SuppressionScope = field(default_factory=SuppressionScope)
