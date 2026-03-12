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
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import NamedTuple

import re2  # google-re2: O(N) guaranteed

from abicheck.core.model import Change, ChangeSeverity
from abicheck.core.suppressions.rule import SuppressionRule


class _CompiledRule(NamedTuple):
    """A SuppressionRule with pre-compiled RE2 patterns."""
    rule: SuppressionRule
    glob_pattern: str | None          # raw glob (for fnmatch)
    regex_compiled: re2.Pattern | None  # pre-compiled RE2


@dataclass
class SuppressionResult:
    """Result of applying suppression rules to a list of Changes."""
    active: list[Change] = field(default_factory=list)      # not suppressed
    suppressed: list[Change] = field(default_factory=list)  # matched a rule
    match_map: dict[int, SuppressionRule] = field(default_factory=dict)
    # match_map: id(change) → matching rule (for audit trail)


class SuppressionEngine:
    """Applies SuppressionRules to a list of Changes.

    All patterns are compiled at __init__ time — never inside the match loop.
    Uses RE2 for regex matching: O(N) guaranteed, safe for untrusted patterns.

    Priority: rules are evaluated in order; first match wins.
    """

    def __init__(self, rules: list[SuppressionRule]) -> None:
        self._compiled: list[_CompiledRule] = []
        for rule in rules:
            compiled_regex = None
            if rule.entity_regex is not None:
                try:
                    compiled_regex = re2.compile(rule.entity_regex)
                except Exception as exc:  # re2 raises re2._re2.Error, not stdlib re.error
                    raise ValueError(
                        f"Invalid RE2 pattern in suppression rule "
                        f"(reason={rule.reason!r}): {rule.entity_regex!r} — {exc}"
                    ) from exc
            self._compiled.append(_CompiledRule(
                rule=rule,
                glob_pattern=rule.entity_glob,
                regex_compiled=compiled_regex,
            ))

    def apply(self, changes: list[Change]) -> SuppressionResult:
        """Apply all rules to a list of Changes. Returns SuppressionResult."""
        result = SuppressionResult()
        for change in changes:
            matched_rule = self._match(change)
            if matched_rule is not None:
                # Return a new Change with severity SUPPRESSED (Change is a frozen-ish dataclass)
                suppressed = _with_severity(change, ChangeSeverity.SUPPRESSED)
                result.suppressed.append(suppressed)
                result.match_map[id(suppressed)] = matched_rule
            else:
                result.active.append(change)
        return result

    def _match(self, change: Change) -> SuppressionRule | None:
        """Return the first matching rule, or None."""
        for cr in self._compiled:
            if self._rule_matches(cr, change):
                return cr.rule
        return None

    def _rule_matches(self, cr: _CompiledRule, change: Change) -> bool:
        rule = cr.rule

        # change_kind filter
        if rule.change_kind is not None:
            if change.change_kind.value != rule.change_kind:
                return False

        # scope: platform (skip — no platform field on Change yet; Phase 3)
        # scope: profile (skip — no profile field on Change yet; Phase 4)
        # scope: version_range (skip — Phase 2b)

        # entity_glob match (fnmatch for shell-style patterns)
        if cr.glob_pattern is not None:
            if not fnmatch.fnmatch(change.entity_name, cr.glob_pattern):
                return False

        # entity_regex match (RE2, pre-compiled)
        if cr.regex_compiled is not None:
            if not cr.regex_compiled.search(change.entity_name):
                return False

        return True


def _with_severity(change: Change, severity: ChangeSeverity) -> Change:
    """Return a copy of Change with a different severity (dataclass replace)."""
    from dataclasses import replace
    return replace(change, severity=severity)
