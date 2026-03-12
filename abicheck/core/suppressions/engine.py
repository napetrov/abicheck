"""Suppression Engine — v0.2.

Matches Changes against SuppressionRules using RE2 for guaranteed O(N) performance.

Requirements (from plan):
- MANDATORY: use google-re2 (pyre2) — O(N) guaranteed, no backtracking DoS
- Pre-compile ALL patterns at rule load time (NEVER inside match loop)
- Priority order: CLI > repository > user defaults > system defaults

Usage::

    engine = SuppressionEngine(rules)
    result = engine.apply(changes)
    # result.suppressed → list[Change] that matched a rule (severity → SUPPRESSED)
    # result.active     → list[Change] not suppressed

Phase 2b: version_range matching is implemented.
  Pass version_context to __init__ or apply() to enable range filtering.
  When version_context=None, the range filter is skipped (conservative: suppress
  if other fields match). This is safe because the Change model does not yet have
  a version field; version context must be supplied by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, NamedTuple

import re2  # google-re2: O(N) guaranteed

from abicheck.core.errors import SuppressionError
from abicheck.core.model import Change, ChangeSeverity
from abicheck.core.pipeline import KNOWN_PLATFORMS as _KNOWN_PLATFORMS  # noqa: PLC0415
from abicheck.core.pipeline import KNOWN_PROFILES as _KNOWN_PROFILES
from abicheck.core.suppressions.rule import SuppressionRule, VersionRange

# ---------------------------------------------------------------------------
# Input length limits (security hardening)
# ---------------------------------------------------------------------------
_MAX_GLOB_LEN = 500
_MAX_REGEX_LEN = 500
_MAX_REASON_LEN = 1000


# ---------------------------------------------------------------------------
# Version comparison helpers (Phase 2b)
# ---------------------------------------------------------------------------

def _parse_semver(v: str) -> object:
    """Parse a semver string using packaging.version.Version."""
    try:
        from packaging.version import Version  # noqa: PLC0415
        return Version(v)
    except Exception as exc:
        raise ValueError(f"Invalid semver version {v!r}: {exc}") from exc


def _parse_intel_quarterly(v: str) -> tuple[int, int]:
    """Parse Intel quarterly notation '2024.1' → (2024, 1).

    Year must be a positive integer. Quarter must be in 1..4.
    """
    parts = v.split(".")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid intel_quarterly version {v!r}: expected 'YEAR.QUARTER' format"
        )
    try:
        year, quarter = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(
            f"Invalid intel_quarterly version {v!r}: {exc}"
        ) from exc
    if quarter < 1 or quarter > 4:
        raise ValueError(
            f"Invalid intel_quarterly version {v!r}: quarter must be 1..4, got {quarter}"
        )
    if year <= 0:
        raise ValueError(
            f"Invalid intel_quarterly version {v!r}: year must be positive, got {year}"
        )
    return (year, quarter)


def _parse_linear(v: str) -> int | str:
    """Parse a linear version: try int, fall back to string.

    Returns a consistent type so that both bounds are comparable.
    Callers must ensure both bounds use the same type (both int or both str).
    """
    try:
        return int(v)
    except ValueError:
        return v


def _cmp_in_range(v: Any, from_: Any, to_: Any, inclusive: bool) -> bool:
    """Check if v is within [from_, to_] (or open-ended when None)."""
    if from_ is not None:
        if inclusive:
            if v < from_:
                return False
        else:
            if v <= from_:
                return False
    if to_ is not None:
        if inclusive:
            if v > to_:
                return False
        else:
            if v >= to_:
                return False
    return True


def _version_in_range(version: str, vr: VersionRange) -> bool:
    """Check whether ``version`` falls within ``vr``.

    Handles semver, intel_quarterly, and linear schemes.
    Both ``from_version`` and ``to_version`` may be None (open-ended bounds).
    ``inclusive=True`` uses closed range [from, to].
    """
    scheme = vr.scheme

    if scheme == "semver":
        v = _parse_semver(version)
        from_ = _parse_semver(vr.from_version) if vr.from_version is not None else None
        to_ = _parse_semver(vr.to_version) if vr.to_version is not None else None
        return _cmp_in_range(v, from_, to_, vr.inclusive)

    if scheme == "intel_quarterly":
        v_q = _parse_intel_quarterly(version)
        from_q = _parse_intel_quarterly(vr.from_version) if vr.from_version is not None else None
        to_q = _parse_intel_quarterly(vr.to_version) if vr.to_version is not None else None
        return _cmp_in_range(v_q, from_q, to_q, vr.inclusive)

    if scheme == "linear":
        v_l = _parse_linear(version)
        from_l = _parse_linear(vr.from_version) if vr.from_version is not None else None
        to_l = _parse_linear(vr.to_version) if vr.to_version is not None else None
        # Type mismatch (int vs str) — skip filter conservatively (return True)
        if isinstance(v_l, int) != isinstance(from_l, int) and from_l is not None:
            return True
        if isinstance(v_l, int) != isinstance(to_l, int) and to_l is not None:
            return True
        return _cmp_in_range(v_l, from_l, to_l, vr.inclusive)

    raise ValueError(f"Unknown version range scheme: {scheme!r}")


def _validate_version_range(vr: VersionRange) -> None:
    """Pre-validate a VersionRange at load time, raising SuppressionError if invalid."""
    scheme = vr.scheme
    if scheme == "semver":
        if vr.from_version is not None:
            try:
                _parse_semver(vr.from_version)
            except ValueError as exc:
                raise SuppressionError(
                    f"Invalid from_version in version_range: {exc}"
                ) from exc
        if vr.to_version is not None:
            try:
                _parse_semver(vr.to_version)
            except ValueError as exc:
                raise SuppressionError(
                    f"Invalid to_version in version_range: {exc}"
                ) from exc
        return

    if scheme == "intel_quarterly":
        if vr.from_version is not None:
            try:
                _parse_intel_quarterly(vr.from_version)
            except ValueError as exc:
                raise SuppressionError(
                    f"Invalid from_version in version_range: {exc}"
                ) from exc
        if vr.to_version is not None:
            try:
                _parse_intel_quarterly(vr.to_version)
            except ValueError as exc:
                raise SuppressionError(
                    f"Invalid to_version in version_range: {exc}"
                ) from exc
        return

    if scheme == "linear":
        parsed_from: int | str | None = None
        parsed_to: int | str | None = None
        if vr.from_version is not None:
            parsed_from = _parse_linear(vr.from_version)
        if vr.to_version is not None:
            parsed_to = _parse_linear(vr.to_version)
        if parsed_from is not None and parsed_to is not None and type(parsed_from) is not type(parsed_to):
            raise SuppressionError(
                "Invalid linear version_range bounds: from_version and to_version "
                f"must be comparable (both int or both str), got "
                f"{type(parsed_from).__name__} and {type(parsed_to).__name__}"
            )
        return

    raise SuppressionError(f"Unknown version range scheme: {scheme!r}")


# ---------------------------------------------------------------------------
# Compiled rule structure
# ---------------------------------------------------------------------------

class _CompiledRule(NamedTuple):
    """A SuppressionRule with pre-compiled RE2 patterns."""
    rule: SuppressionRule
    glob_re: re2.Pattern | None       # pre-compiled RE2 from glob (via fnmatch.translate)
    regex_compiled: re2.Pattern | None  # pre-compiled RE2 from entity_regex
    namespace_re: re2.Pattern | None   # pre-compiled RE2 from namespace_pattern
    version_range: VersionRange | None  # Phase 2b: pre-validated version range
    platform: str | None               # Phase 3: "elf" | "pe" | "macho" | None=any
    profile: str | None                # Phase 4: "c" | "cpp" | "sycl" | None=any


# Stable key for match_map audit trail: (entity_type, entity_name, change_kind)
# Using a tuple instead of id(change) ensures the audit trail survives copies/serialization.
_MatchKey = tuple[str, str, str]


@dataclass
class SuppressionResult:
    """Result of applying suppression rules to a list of Changes."""
    active: list[Change] = field(default_factory=list)      # not suppressed
    suppressed: list[Change] = field(default_factory=list)  # matched a rule
    match_map: dict[_MatchKey, SuppressionRule] = field(default_factory=dict)
    # match_map: (entity_type, entity_name, change_kind.value) → matching rule (audit trail)


class SuppressionEngine:
    """Applies SuppressionRules to a list of Changes.

    All patterns are compiled at __init__ time — never inside the match loop.
    Uses RE2 for regex matching: O(N) guaranteed, safe for untrusted patterns.

    Priority: rules are evaluated in order; first match wins.

    Phase 2b: version_context parameter enables version range filtering.
    When version_context is None, version_range checks are skipped (conservative).

    Phase 3: platform_context parameter enables scope.platform filtering.
    When platform_context is None, platform checks are skipped (conservative: suppress).

    Phase 4: profile_context parameter enables scope.profile filtering.
    When profile_context is None, profile checks are skipped (conservative: suppress).
    """

    def __init__(
        self,
        rules: list[SuppressionRule],
        version_context: str | None = None,
        platform_context: str | None = None,
        profile_context: str | None = None,
    ) -> None:
        self._version_context = version_context
        self._platform_context = platform_context
        self._profile_context = profile_context
        self._compiled: list[_CompiledRule] = []
        for rule in rules:
            # ── Security: enforce input length limits ──────────────────────
            if rule.entity_glob is not None and len(rule.entity_glob) > _MAX_GLOB_LEN:
                raise SuppressionError(
                    f"entity_glob too long (max {_MAX_GLOB_LEN} chars)"
                )
            if rule.entity_regex is not None and len(rule.entity_regex) > _MAX_REGEX_LEN:
                raise SuppressionError(
                    f"entity_regex too long (max {_MAX_REGEX_LEN} chars)"
                )
            if len(rule.reason) > _MAX_REASON_LEN:
                raise SuppressionError(
                    f"reason too long (max {_MAX_REASON_LEN} chars)"
                )

            # Compile glob → RE2 (eliminates stdlib re via fnmatch)
            glob_re = None
            if rule.entity_glob is not None:
                try:
                    glob_re = _glob_to_re2(rule.entity_glob)
                except Exception as exc:
                    raise SuppressionError(
                        f"Invalid glob pattern in suppression rule "
                        f"(reason={rule.reason!r}): {rule.entity_glob!r} — {exc}"
                    ) from exc

            compiled_regex = None
            if rule.entity_regex is not None:
                try:
                    compiled_regex = re2.compile(rule.entity_regex)
                except Exception as exc:  # re2 raises re2._re2.Error, not stdlib re.error
                    raise SuppressionError(
                        f"Invalid RE2 pattern in suppression rule "
                        f"(reason={rule.reason!r}): {rule.entity_regex!r} — {exc}"
                    ) from exc

            # Namespace pattern: compile RE2 for namespace prefix matching
            namespace_re = None
            if rule.namespace_pattern is not None:
                if len(rule.namespace_pattern) > _MAX_REGEX_LEN:
                    raise SuppressionError(
                        f"namespace_pattern too long (max {_MAX_REGEX_LEN} chars)"
                    )
                try:
                    namespace_re = re2.compile(rule.namespace_pattern)
                except Exception as exc:
                    raise SuppressionError(
                        f"Invalid namespace_pattern in suppression rule "
                        f"(reason={rule.reason!r}): {rule.namespace_pattern!r} — {exc}"
                    ) from exc

            # Phase 3: validate scope.platform value
            scope = rule.scope
            compiled_platform: str | None = None
            if scope.platform is not None:
                if scope.platform not in _KNOWN_PLATFORMS:
                    raise SuppressionError(
                        f"Unknown platform {scope.platform!r} in suppression rule "
                        f"(reason={rule.reason!r}). "
                        f"Valid values: {sorted(_KNOWN_PLATFORMS)}"
                    )
                compiled_platform = scope.platform

            # Phase 4: validate scope.profile value
            compiled_profile: str | None = None
            if scope.profile is not None:
                if scope.profile not in _KNOWN_PROFILES:
                    raise SuppressionError(
                        f"Unknown profile {scope.profile!r} in suppression rule "
                        f"(reason={rule.reason!r}). "
                        f"Valid values: {sorted(_KNOWN_PROFILES)}"
                    )
                compiled_profile = scope.profile

            # Phase 2b: pre-validate version_range at load time
            compiled_vr: VersionRange | None = None
            if scope.version_range is not None:
                _validate_version_range(scope.version_range)
                compiled_vr = scope.version_range

            self._compiled.append(_CompiledRule(
                rule=rule,
                glob_re=glob_re,
                regex_compiled=compiled_regex,
                namespace_re=namespace_re,
                version_range=compiled_vr,
                platform=compiled_platform,
                profile=compiled_profile,
            ))

    def apply(
        self,
        changes: list[Change],
        version_context: str | None = None,
        platform_context: str | None = None,
        profile_context: str | None = None,
    ) -> SuppressionResult:
        """Apply all rules to a list of Changes. Returns SuppressionResult.

        version_context/platform_context/profile_context override init-time values.
        Non-None values override init; None falls back to init value.
        """
        effective_version = version_context if version_context is not None else self._version_context
        effective_platform = platform_context if platform_context is not None else self._platform_context
        effective_profile = profile_context if profile_context is not None else self._profile_context
        if effective_platform is not None and effective_platform not in _KNOWN_PLATFORMS:
            raise SuppressionError(
                f"Unknown platform_context {effective_platform!r}. "
                f"Valid values: {sorted(_KNOWN_PLATFORMS)}"
            )
        if effective_profile is not None and effective_profile not in _KNOWN_PROFILES:
            raise SuppressionError(
                f"Unknown profile_context {effective_profile!r}. "
                f"Valid values: {sorted(_KNOWN_PROFILES)}"
            )
        result = SuppressionResult()
        for change in changes:
            matched_rule = self._match(change, effective_version, effective_platform, effective_profile)
            if matched_rule is not None:
                # Return a new Change with severity SUPPRESSED (Change is a frozen-ish dataclass)
                suppressed = _with_severity(change, ChangeSeverity.SUPPRESSED)
                result.suppressed.append(suppressed)
                key: _MatchKey = (
                    change.entity_type.value,
                    change.entity_name,
                    change.change_kind.value,
                )
                result.match_map[key] = matched_rule
            else:
                result.active.append(change)
        return result

    def _match(
        self,
        change: Change,
        version_context: str | None,
        platform_context: str | None,
        profile_context: str | None,
    ) -> SuppressionRule | None:
        """Return the first matching rule, or None."""
        for cr in self._compiled:
            if self._rule_matches(cr, change, version_context, platform_context, profile_context):
                return cr.rule
        return None

    def _rule_matches(
        self,
        cr: _CompiledRule,
        change: Change,
        version_context: str | None,
        platform_context: str | None,
        profile_context: str | None,
    ) -> bool:
        rule = cr.rule

        # change_kind filter
        if rule.change_kind is not None:
            if change.change_kind.value != rule.change_kind:
                return False

        # Phase 3: platform filter
        # When platform_context is provided AND a platform is set on the rule, apply filter.
        # When platform_context is None, skip (conservative: suppress if other fields match).
        if cr.platform is not None and platform_context is not None:
            if cr.platform != platform_context:
                return False

        # Phase 4: profile filter
        # When profile_context is provided AND a profile is set on the rule, apply filter.
        # When profile_context is None, skip (conservative: suppress if other fields match).
        if cr.profile is not None and profile_context is not None:
            if cr.profile != profile_context:
                return False

        # Phase 2b: version_range filter
        # When version_context is provided AND a version_range is set, apply the filter.
        # When version_context is None, skip the filter (conservative: suppress matches).
        if cr.version_range is not None and version_context is not None:
            try:
                if not _version_in_range(version_context, cr.version_range):
                    return False
            except ValueError:
                # Invalid version string at match time → skip this filter conservatively
                pass

        # entity_glob match (RE2, pre-compiled from glob pattern)
        if cr.glob_re is not None:
            if not cr.glob_re.match(change.entity_name):
                return False

        # entity_regex match (RE2, pre-compiled) — fullmatch for full-string safety
        if cr.regex_compiled is not None:
            if not cr.regex_compiled.fullmatch(change.entity_name):
                return False

        # namespace_pattern match: extract namespace prefix (before last '::')
        # and fullmatch against the compiled namespace RE2 pattern.
        # Entity names without '::' have no namespace → namespace prefix is "".
        # Example: "internal::Foo::bar" → namespace prefix = "internal::Foo"
        if cr.namespace_re is not None:
            sep = change.entity_name.rfind("::")
            ns_prefix = change.entity_name[:sep] if sep != -1 else ""
            if not cr.namespace_re.fullmatch(ns_prefix):
                return False

        return True


def _with_severity(change: Change, severity: ChangeSeverity) -> Change:
    """Return a copy of Change with a different severity."""
    return replace(change, severity=severity)


def _glob_to_re2(pattern: str) -> re2.Pattern:
    r"""Convert a shell-style glob to a pre-compiled RE2 pattern.

    fnmatch.translate() produces Python-specific anchors (\\Z) not supported by RE2.
    We convert: * → .*, ? → ., [abc] → [abc], and anchor with ^ and $.
    """
    result = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == '*':
            result.append('.*')
        elif c == '?':
            result.append('.')
        elif c == '[':
            # pass through character classes; convert shell negation [!...] → RE2 [^...]
            j = pattern.find(']', i + 1)
            if j == -1:
                result.append(re2.escape(c))
            else:
                char_class = pattern[i:j + 1]
                if char_class.startswith('[!'):
                    # [!abc] → [^abc]: shell negation → RE2 negation
                    char_class = '[^' + char_class[2:]
                result.append(char_class)
                i = j
        else:
            result.append(re2.escape(c))
        i += 1
    return re2.compile('^' + ''.join(result) + '$')
