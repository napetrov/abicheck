from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from abicheck.checker_policy import ChangeKind, Verdict
from abicheck.policy_file import PolicyFile


def _change(kind: ChangeKind):
    c = MagicMock()
    c.kind = kind
    return c


def test_policy_file_defaults_when_empty(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")

    pf = PolicyFile.load(p)
    assert pf.base_policy == "strict_abi"
    assert pf.overrides == {}


def test_policy_file_applies_overrides(tmp_path: Path) -> None:
    p = tmp_path / "policy.yaml"
    p.write_text(
        """
base_policy: strict_abi
overrides:
  enum_member_renamed: ignore
  calling_convention_changed: warn
""".strip(),
        encoding="utf-8",
    )

    pf = PolicyFile.load(p)

    assert pf.compute_verdict([_change(ChangeKind.ENUM_MEMBER_RENAMED)]) == Verdict.COMPATIBLE
    assert pf.compute_verdict([_change(ChangeKind.CALLING_CONVENTION_CHANGED)]) == Verdict.API_BREAK


def test_policy_file_unknown_base_policy_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("base_policy: custom", encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown base_policy"):
        PolicyFile.load(p)


def test_policy_file_invalid_severity_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad_severity.yaml"
    p.write_text(
        """
overrides:
  enum_member_renamed: maybe
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid severity"):
        PolicyFile.load(p)
