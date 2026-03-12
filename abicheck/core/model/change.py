"""Change model — v0.2.

Represents a single detected difference between two Corpus snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .origin import Origin


class ChangeSeverity(str, Enum):
    """Severity of a detected change.

    Replaces the v0.1 ``requires_review: bool`` field.
    This field carries *epistemic* information (detection confidence),
    not just policy intent — which is why it lives on Change, not only PolicyResult.
    """

    BREAK = "break"  # ABI-incompatible
    COMPATIBLE_EXTENSION = "compatible_extension"  # additive, safe
    REVIEW_NEEDED = "review_needed"  # uncertain, needs human review
    SUPPRESSED = "suppressed"  # matched a suppression rule


class ChangeKind(str, Enum):
    """Category of the detected change."""

    SYMBOL = "symbol"
    TYPE_LAYOUT = "type_layout"
    SIZE_CHANGE = "size_change"  # struct/class total size (distinct from field layout)
    CALLING_CONVENTION = "calling_convention"  # only emitted when DWARF/castxml evidence present
    VTABLE_INHERITANCE = "vtable_inheritance"
    LOADER_METADATA = "loader_metadata"
    PACKAGING_RUNTIME = "packaging_runtime"
    SOURCE_API_ONLY = "source_api_only"


class EntityType(str, Enum):
    """Type of entity involved in a change."""

    FUNCTION = "function"
    VARIABLE = "variable"
    TYPE = "type"
    FIELD = "field"


@dataclass(slots=True)
class SourceLocation:
    """File + line reference from DWARF or castxml."""

    file: str
    line: int | None = None
    column: int | None = None

    def __str__(self) -> str:
        if self.line is not None and self.column is not None:
            return f"{self.file}:{self.line}:{self.column}"
        if self.line is not None:
            return f"{self.file}:{self.line}"
        return self.file


@dataclass(slots=True)
class EntitySnapshot:
    """Typed snapshot of an entity before or after a change.

    Using a typed wrapper instead of plain dict/str prevents isinstance()
    sprawl in the report layer.
    """

    entity_repr: str  # human-readable (demangled name / type signature)
    raw: dict[str, Any] = field(default_factory=dict)  # full structured data


@dataclass(slots=True)
class Change:
    """A single detected ABI/API change between two Corpus snapshots.

    Design notes:
    - ``origin`` is the primary (highest-confidence) source
    - ``corroborating`` holds additional sources that confirm the change
      (tuple, not list — lower overhead; empty tuple is the common case)
    - ``severity`` carries epistemic info about detection confidence,
      not only policy intent
    - ``calling_convention`` kind MUST NOT be emitted without DWARF/castxml evidence;
      binary-only → severity=REVIEW_NEEDED
    """

    change_kind: ChangeKind
    entity_type: EntityType
    entity_name: str
    before: EntitySnapshot
    after: EntitySnapshot
    severity: ChangeSeverity
    origin: Origin  # primary (highest confidence)
    corroborating: tuple[Origin, ...] = ()  # additional confirming sources
    confidence: float = 1.0  # 0.0–1.0
    location: SourceLocation | None = None  # file/line from DWARF or castxml

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")
        if self.origin in self.corroborating:
            raise ValueError(
                f"primary origin {self.origin!r} must not appear in corroborating"
            )
        if len(self.corroborating) != len(set(self.corroborating)):
            raise ValueError("corroborating origins must be unique")
        # Primary origin must have the highest confidence among all sources
        all_origins = (self.origin, *self.corroborating)
        if self.corroborating and self.origin != Origin.highest(all_origins):
            raise ValueError(
                f"primary origin {self.origin!r} must be the highest-confidence source; "
                f"use origin={Origin.highest(all_origins)!r} instead"
            )
        if self.change_kind == ChangeKind.CALLING_CONVENTION:
            evidence = (self.origin, *self.corroborating)
            if Origin.DWARF not in evidence and Origin.CASTXML not in evidence:
                raise ValueError(
                    "CALLING_CONVENTION requires DWARF or CASTXML evidence; "
                    "binary-only sources must use severity=REVIEW_NEEDED instead"
                )

    @property
    def requires_review(self) -> bool:
        """Backward-compat shim. Use severity == REVIEW_NEEDED directly."""
        return self.severity == ChangeSeverity.REVIEW_NEEDED
