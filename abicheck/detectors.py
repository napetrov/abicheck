"""Detector contracts used by checker orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .model import AbiSnapshot


class ChangeLike(Protocol):
    kind: object
    symbol: str
    description: str


class Detector(Protocol):
    name: str
    description: str

    def run(self, old: AbiSnapshot, new: AbiSnapshot) -> list[ChangeLike]:
        ...

    def is_supported(self, old: AbiSnapshot, new: AbiSnapshot) -> tuple[bool, str | None]:
        ...


@dataclass(frozen=True)
class DetectorResult:
    name: str
    changes_count: int
    enabled: bool = True
    coverage_gap: str | None = None
