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

"""Suppression — load and apply suppression rules to ABI changes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from .checker import Change, ChangeKind

# Pre-build valid change_kind values for fast validation
_VALID_CHANGE_KINDS: frozenset[str] = frozenset(ck.value for ck in ChangeKind)

# Keys allowed in a suppression entry — unknown keys are rejected
_KNOWN_ENTRY_KEYS: frozenset[str] = frozenset({
    "symbol", "symbol_pattern", "type_pattern", "change_kind", "reason",
    "label", "source_location", "expires",
})

# ChangeKind values that represent type-level changes (matched by type_pattern)
_TYPE_CHANGE_KINDS: frozenset[str] = frozenset({
    "type_size_changed", "type_alignment_changed", "type_field_removed",
    "type_field_added", "type_field_offset_changed", "type_field_type_changed",
    "type_base_changed", "type_vtable_changed", "type_added", "type_removed",
    "type_field_added_compatible", "type_became_opaque", "type_visibility_changed",
    "enum_member_removed", "enum_member_added", "enum_member_value_changed",
    "enum_last_member_value_changed", "enum_member_renamed",
    "enum_underlying_size_changed",
    "typedef_removed", "typedef_base_changed",
    "struct_field_type_changed", "union_field_type_changed",
})


@dataclass
class Suppression:
    symbol: str | None = None
    symbol_pattern: str | None = None
    type_pattern: str | None = None
    change_kind: str | None = None
    reason: str | None = None
    # --- Extended fields ---
    label: str | None = None
    """Optional tag/label for grouping suppressions (e.g. 'workaround', 'internal')."""
    source_location: str | None = None
    """Suppress all changes whose source file path matches this pattern (fnmatch-style).
    Example: ``source_location: "*/internal/*"`` suppresses changes from internal headers."""
    expires: date | None = None
    """Optional expiry date (ISO 8601). After this date, the suppression is inactive
    and a warning is emitted. Format: ``expires: 2026-06-01``."""
    _compiled_pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)
    _compiled_type_pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)
    _compiled_source_pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        has_symbol = self.symbol is not None
        has_sym_pattern = self.symbol_pattern is not None
        has_type_pattern = self.type_pattern is not None
        has_source_location = self.source_location is not None

        selector_count = sum([has_symbol, has_sym_pattern, has_type_pattern])
        if selector_count == 0 and not has_source_location:
            raise ValueError(
                "Suppression must have at least one of: "
                "'symbol', 'symbol_pattern', 'type_pattern', or 'source_location'"
            )
        if selector_count > 1:
            raise ValueError(
                "Suppression fields 'symbol', 'symbol_pattern', and 'type_pattern' "
                "are mutually exclusive — specify exactly one"
            )
        # Compile regex eagerly — malformed patterns fail at load time, not match time.
        # Uses fullmatch semantics: the pattern must match the entire symbol name.
        # Use explicit '.*' anchors in the pattern if partial matching is intended.
        if self.symbol_pattern is not None:
            try:
                self._compiled_pattern = re.compile(self.symbol_pattern)
            except re.error as e:
                raise ValueError(
                    f"Invalid symbol_pattern {self.symbol_pattern!r}: {e}"
                ) from e
        if self.type_pattern is not None:
            try:
                self._compiled_type_pattern = re.compile(self.type_pattern)
            except re.error as e:
                raise ValueError(
                    f"Invalid type_pattern {self.type_pattern!r}: {e}"
                ) from e
        if self.source_location is not None:
            # Convert fnmatch-style glob to regex for flexibility
            import fnmatch
            try:
                self._compiled_source_pattern = re.compile(
                    fnmatch.translate(self.source_location)
                )
            except re.error as e:
                raise ValueError(
                    f"Invalid source_location {self.source_location!r}: {e}"
                ) from e
        # Validate change_kind against known enum values
        if self.change_kind is not None:
            if self.change_kind not in _VALID_CHANGE_KINDS:
                valid = ", ".join(sorted(_VALID_CHANGE_KINDS))
                raise ValueError(
                    f"Unknown change_kind {self.change_kind!r}. "
                    f"Valid values: {valid}"
                )

    def is_expired(self, today: date | None = None) -> bool:
        """Return True if this suppression has passed its expiry date."""
        if self.expires is None:
            return False
        check_date = today or date.today()
        return check_date > self.expires

    def matches(self, change: Change, today: date | None = None) -> bool:
        """Return True if this suppression rule matches the given change.

        Expired suppressions (past ``expires`` date) never match.

        Pattern matching uses fullmatch — the pattern must cover the entire
        mangled symbol name. Use '.*foo.*' for substring matching.

        ``source_location`` uses fnmatch-style glob against
        ``change.source_location``.

        type_pattern only matches changes whose kind is a type-level change
        (TYPE_*, ENUM_*, TYPEDEF_*, etc.), preventing type whitelists from
        suppressing symbol-level changes.
        """
        # Expired suppressions are inactive
        if self.is_expired(today):
            return False

        # source_location: match against change.source_location if present
        if self._compiled_source_pattern is not None:
            src = change.source_location or ""
            if not self._compiled_source_pattern.match(src):
                return False
            # Fall through to check remaining selectors conjunctively (AND logic)

        # type_pattern: only matches type-level changes
        if self._compiled_type_pattern is not None:
            if change.kind.value not in _TYPE_CHANGE_KINDS:
                return False
            if not self._compiled_type_pattern.fullmatch(change.symbol):
                return False
            # Check change_kind filter if specified
            if self.change_kind is not None and change.kind.value != self.change_kind:
                return False
            return True

        # Check symbol match
        if self.symbol is not None:
            if change.symbol != self.symbol:
                return False
        elif self._compiled_pattern is not None:
            # fullmatch: pattern must cover the complete symbol, preventing
            # accidental over-suppression from short patterns.
            if not self._compiled_pattern.fullmatch(change.symbol):
                return False

        # Check change_kind match (if specified)
        if self.change_kind is not None:
            if change.kind.value != self.change_kind:
                return False

        return True


class SuppressionList:
    def __init__(self, suppressions: list[Suppression]) -> None:
        self._suppressions = suppressions

    @classmethod
    def merge(cls, a: SuppressionList, b: SuppressionList) -> SuppressionList:
        """Return a new SuppressionList combining rules from both lists."""
        return cls(suppressions=[*a._suppressions, *b._suppressions])

    @classmethod
    def load(cls, path: Path) -> SuppressionList:
        """Load suppression rules from a YAML file.

        Raises ValueError on schema violations, unknown keys, bad regex,
        or invalid change_kind values.
        Raises OSError if the file cannot be read.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise OSError(f"Cannot read suppression file {path}: {e}") from e

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in suppression file: {e}") from e

        if not isinstance(data, dict):
            raise ValueError("Suppression file must be a YAML mapping")

        version = data.get("version")
        if version != 1:
            raise ValueError(f"Unsupported suppression file version: {version!r} (expected 1)")

        raw_suppressions = data.get("suppressions")
        if raw_suppressions is None:
            return cls([])
        if not isinstance(raw_suppressions, list):
            raise ValueError("'suppressions' must be a list")

        suppressions: list[Suppression] = []
        for i, item in enumerate(raw_suppressions):
            if not isinstance(item, dict):
                raise ValueError(f"Suppression entry {i} must be a mapping")
            # Reject unknown keys — catches typos like 'symbl' or 'cahnge_kind'
            unknown = set(item.keys()) - _KNOWN_ENTRY_KEYS
            if unknown:
                raise ValueError(
                    f"Suppression entry {i} has unknown key(s): {sorted(unknown)}. "
                    f"Allowed keys: {sorted(_KNOWN_ENTRY_KEYS)}"
                )
            # Parse expires date
            expires_raw = item.get("expires")
            expires: date | None = None
            if expires_raw is not None:
                if isinstance(expires_raw, date):
                    # datetime is a subclass of date; convert to date to avoid
                    # TypeError when comparing datetime to date in is_expired()
                    if isinstance(expires_raw, datetime):
                        expires = expires_raw.date()
                    else:
                        expires = expires_raw
                else:
                    try:
                        expires = date.fromisoformat(str(expires_raw))
                    except ValueError as e:
                        raise ValueError(
                            f"Suppression entry {i}: invalid 'expires' date {expires_raw!r} "
                            "(expected ISO 8601 format, e.g. 2026-06-01)"
                        ) from e
            try:
                sup = Suppression(
                    symbol=item.get("symbol"),
                    symbol_pattern=item.get("symbol_pattern"),
                    type_pattern=item.get("type_pattern"),
                    change_kind=item.get("change_kind"),
                    reason=item.get("reason"),
                    label=item.get("label"),
                    source_location=item.get("source_location"),
                    expires=expires,
                )
            except ValueError as e:
                raise ValueError(f"Suppression entry {i}: {e}") from e
            suppressions.append(sup)

        return cls(suppressions)

    def is_suppressed(self, change: Change, today: date | None = None) -> bool:
        """Return True if any active (non-expired) suppression rule matches the given change."""
        return any(s.matches(change, today=today) for s in self._suppressions)

    def expired_rules(self, today: date | None = None) -> list[Suppression]:
        """Return all rules that have passed their expiry date."""
        return [s for s in self._suppressions if s.is_expired(today)]

    def rules_by_label(self, label: str) -> list[Suppression]:
        """Return all rules with the given label."""
        return [s for s in self._suppressions if s.label == label]

    def __len__(self) -> int:
        return len(self._suppressions)

    def __repr__(self) -> str:
        return f"SuppressionList({len(self._suppressions)} rules)"
