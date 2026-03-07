"""Suppression — load and apply suppression rules to ABI changes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .checker import Change, ChangeKind

# Pre-build valid change_kind values for fast validation
_VALID_CHANGE_KINDS: frozenset[str] = frozenset(ck.value for ck in ChangeKind)


@dataclass
class Suppression:
    symbol: str | None = None
    symbol_pattern: str | None = None
    change_kind: str | None = None
    reason: str | None = None
    _compiled_pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.symbol is not None and self.symbol_pattern is not None:
            raise ValueError(
                "Suppression cannot have both 'symbol' and 'symbol_pattern'"
            )
        if self.symbol is None and self.symbol_pattern is None:
            raise ValueError(
                "Suppression must have either 'symbol' or 'symbol_pattern'"
            )
        # Compile regex eagerly so malformed patterns fail at load time
        if self.symbol_pattern is not None:
            try:
                self._compiled_pattern = re.compile(self.symbol_pattern)
            except re.error as e:
                raise ValueError(
                    f"Invalid symbol_pattern {self.symbol_pattern!r}: {e}"
                ) from e
        # Validate change_kind against known values
        if self.change_kind is not None:
            if self.change_kind not in _VALID_CHANGE_KINDS:
                valid = ", ".join(sorted(_VALID_CHANGE_KINDS))
                raise ValueError(
                    f"Unknown change_kind {self.change_kind!r}. "
                    f"Valid values: {valid}"
                )

    def matches(self, change: Change) -> bool:
        """Return True if this suppression rule matches the given change."""
        # Check symbol match
        if self.symbol is not None:
            if change.symbol != self.symbol:
                return False
        elif self._compiled_pattern is not None:
            if not self._compiled_pattern.search(change.symbol):
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
    def load(cls, path: Path) -> SuppressionList:
        """Load suppression rules from a YAML file."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
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
