"""Suppression — load and apply suppression rules to ABI changes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .checker import Change


@dataclass
class Suppression:
    symbol: Optional[str] = None
    symbol_pattern: Optional[str] = None
    change_kind: Optional[str] = None
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.symbol is not None and self.symbol_pattern is not None:
            raise ValueError(
                "Suppression cannot have both 'symbol' and 'symbol_pattern'"
            )
        if self.symbol is None and self.symbol_pattern is None:
            raise ValueError(
                "Suppression must have either 'symbol' or 'symbol_pattern'"
            )

    def matches(self, change: Change) -> bool:
        """Return True if this suppression rule matches the given change."""
        # Check symbol match
        if self.symbol is not None:
            if change.symbol != self.symbol:
                return False
        elif self.symbol_pattern is not None:
            if not re.search(self.symbol_pattern, change.symbol):
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
    def load(cls, path: Path) -> "SuppressionList":
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
