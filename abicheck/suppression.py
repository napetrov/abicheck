"""Suppression — load and apply suppression rules to ABI changes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .checker import Change, ChangeKind

# Pre-build valid change_kind values for fast validation
_VALID_CHANGE_KINDS: frozenset[str] = frozenset(ck.value for ck in ChangeKind)

# Keys allowed in a suppression entry — unknown keys are rejected
_KNOWN_ENTRY_KEYS: frozenset[str] = frozenset({"symbol", "symbol_pattern", "type_pattern", "change_kind", "reason"})

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
    _compiled_pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)
    _compiled_type_pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        has_symbol = self.symbol is not None
        has_sym_pattern = self.symbol_pattern is not None
        has_type_pattern = self.type_pattern is not None

        if has_symbol and has_sym_pattern:
            raise ValueError(
                "Suppression cannot have both 'symbol' and 'symbol_pattern'"
            )
        if not has_symbol and not has_sym_pattern and not has_type_pattern:
            raise ValueError(
                "Suppression must have 'symbol', 'symbol_pattern', or 'type_pattern'"
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
        # Validate change_kind against known enum values
        if self.change_kind is not None:
            if self.change_kind not in _VALID_CHANGE_KINDS:
                valid = ", ".join(sorted(_VALID_CHANGE_KINDS))
                raise ValueError(
                    f"Unknown change_kind {self.change_kind!r}. "
                    f"Valid values: {valid}"
                )

    def matches(self, change: Change) -> bool:
        """Return True if this suppression rule matches the given change.

        Pattern matching uses fullmatch — the pattern must cover the entire
        mangled symbol name. Use '.*foo.*' for substring matching.

        type_pattern only matches changes whose kind is a type-level change
        (TYPE_*, ENUM_*, TYPEDEF_*, etc.), preventing type whitelists from
        suppressing symbol-level changes.
        """
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
            try:
                sup = Suppression(
                    symbol=item.get("symbol"),
                    symbol_pattern=item.get("symbol_pattern"),
                    change_kind=item.get("change_kind"),
                    reason=item.get("reason"),
                )
            except ValueError as e:
                raise ValueError(f"Suppression entry {i}: {e}") from e
            suppressions.append(sup)

        return cls(suppressions)

    def is_suppressed(self, change: Change) -> bool:
        """Return True if any suppression rule matches the given change."""
        return any(s.matches(change) for s in self._suppressions)

    def __len__(self) -> int:
        return len(self._suppressions)

    def __repr__(self) -> str:
        return f"SuppressionList({len(self._suppressions)} rules)"
