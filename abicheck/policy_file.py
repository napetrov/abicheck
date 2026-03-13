"""Custom policy file support for abicheck.

A policy file is a YAML document that maps ChangeKind names to severity levels,
allowing users to define project-specific verdict rules.

Format example (``my_policy.yaml``)::

    # abicheck policy file
    # Maps ChangeKind slug -> severity: break | warn | ignore
    #
    # break  -> BREAKING verdict (exit code 4)
    # warn   -> API_BREAK verdict (exit code 2)
    # ignore -> COMPATIBLE verdict (exit code 0)
    #
    # Any kind not listed falls back to the base policy (default: strict_abi).

    base_policy: strict_abi          # optional; default strict_abi

    overrides:
      enum_member_renamed:   ignore
      field_renamed:         ignore
      param_renamed:         ignore
      calling_convention_changed: warn

Usage::

    abicheck compare old.json new.json --policy-file my_policy.yaml

Notes:
- ``--policy-file`` overrides ``--policy`` when both are supplied.
- Checks are always executed; only verdict classification changes.
- Unknown kind names emit a warning and are skipped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .checker_policy import ChangeKind, Verdict, compute_verdict, VALID_BASE_POLICIES

log = logging.getLogger(__name__)

# Severity name -> Verdict mapping
_SEVERITY_MAP: dict[str, Verdict] = {
    "break": Verdict.BREAKING,
    "warn": Verdict.API_BREAK,
    "ignore": Verdict.COMPATIBLE,
}

_VALID_BASE_POLICIES = VALID_BASE_POLICIES  # re-export alias for backward compat


@dataclass
class PolicyFile:
    """Parsed custom policy file.

    Attributes:
        base_policy: Base built-in policy to start from (default: ``strict_abi``).
        overrides: Mapping of ChangeKind -> Verdict as specified in the file.
        source_path: Path to the loaded file (for error reporting).
    """

    base_policy: str = "strict_abi"
    overrides: dict[ChangeKind, Verdict] = field(default_factory=dict)
    source_path: Path | None = None

    @classmethod
    def load(cls, path: Path) -> "PolicyFile":
        """Load and validate a policy file from *path*.

        Raises:
            ValueError: If the file is malformed, contains unknown kind names,
                invalid severity strings, or an unknown base_policy.
            OSError: If the file cannot be read.
        """
        try:
            import yaml  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "PyYAML is required for --policy-file support. "
                "Install it with: pip install pyyaml"
            ) from exc

        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            return cls(source_path=path)
        if not isinstance(raw, dict):
            raise ValueError(f"Policy file must be a YAML mapping, got {type(raw).__name__}")

        base_policy = raw.get("base_policy", "strict_abi")
        if base_policy not in _VALID_BASE_POLICIES:
            raise ValueError(
                f"Unknown base_policy {base_policy!r}. "
                f"Valid values: {sorted(_VALID_BASE_POLICIES)}"
            )

        overrides_raw = raw.get("overrides", {})
        if not isinstance(overrides_raw, dict):
            raise ValueError("'overrides' must be a YAML mapping of kind -> severity")

        overrides: dict[ChangeKind, Verdict] = {}
        unknown_kinds: list[str] = []
        unknown_severities: list[str] = []

        slug_to_kind = {k.value: k for k in ChangeKind}

        for slug, severity in overrides_raw.items():
            kind = slug_to_kind.get(str(slug))
            if kind is None:
                unknown_kinds.append(str(slug))
                continue
            verdict = _SEVERITY_MAP.get(str(severity).lower())
            if verdict is None:
                unknown_severities.append(f"{slug}: {severity!r}")
                continue
            overrides[kind] = verdict

        if unknown_kinds:
            log.warning(
                "policy file %s: unknown ChangeKind slugs (skipped): %s",
                path, ", ".join(sorted(unknown_kinds)),
            )
        if unknown_severities:
            raise ValueError(
                f"Invalid severity values in {path}: {unknown_severities}. "
                "Valid values: break, warn, ignore"
            )

        return cls(base_policy=base_policy, overrides=overrides, source_path=path)

    def compute_verdict(self, changes: list[Any]) -> Verdict:
        """Compute verdict for *changes* applying base_policy then overrides.

        Algorithm:
        1. Compute base verdict using the configured base_policy.
        2. For each change, if its kind has an override, apply the override
           verdict (can upgrade or downgrade).
        3. Final verdict = worst (most severe) verdict across all changes.
        """
        if not changes:
            return Verdict.NO_CHANGE

        # Start from base policy verdict
        verdicts: list[Verdict] = []
        for change in changes:
            kind = change.kind
            if kind in self.overrides:
                verdicts.append(self.overrides[kind])
            else:
                # Delegate to base policy for this single change
                single_verdict = compute_verdict([change], policy=self.base_policy)
                verdicts.append(single_verdict)

        # Worst verdict wins
        order = [Verdict.NO_CHANGE, Verdict.COMPATIBLE, Verdict.API_BREAK, Verdict.BREAKING]
        return max(verdicts, key=lambda v: order.index(v) if v in order else 0)

    def describe(self) -> str:
        """Return a human-readable summary of this policy."""
        lines = [f"base_policy: {self.base_policy}"]
        if self.overrides:
            lines.append("overrides:")
            for kind, verdict in sorted(self.overrides.items(), key=lambda x: x[0].value):
                sev = next(s for s, v in _SEVERITY_MAP.items() if v == verdict)
                lines.append(f"  {kind.value}: {sev}")
        else:
            lines.append("overrides: (none)")
        return "\n".join(lines)
