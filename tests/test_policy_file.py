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


def test_policy_file_empty_changes_no_change(tmp_path: Path) -> None:
    p = tmp_path / "empty_policy.yaml"
    p.write_text("overrides: {}\n", encoding="utf-8")

    pf = PolicyFile.load(p)
    assert pf.compute_verdict([]) == Verdict.NO_CHANGE


def test_policy_file_describe_contains_base_and_overrides(tmp_path: Path) -> None:
    p = tmp_path / "policy.yaml"
    p.write_text(
        """
base_policy: sdk_vendor
overrides:
  enum_member_renamed: ignore
""".strip(),
        encoding="utf-8",
    )

    pf = PolicyFile.load(p)
    text = pf.describe()
    assert "base_policy: sdk_vendor" in text
    assert "enum_member_renamed: ignore" in text


def test_policy_file_non_dict_yaml_rejected(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a YAML mapping"):
        PolicyFile.load(p)


def test_policy_file_base_policy_non_string_rejected(tmp_path: Path) -> None:
    p = tmp_path / "list_base.yaml"
    p.write_text("base_policy:\n  - sdk_vendor\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a string"):
        PolicyFile.load(p)


def test_policy_file_overrides_non_dict_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad_overrides.yaml"
    p.write_text("overrides: not_a_mapping\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a YAML mapping"):
        PolicyFile.load(p)


def test_policy_file_mixed_override_and_base(tmp_path: Path) -> None:
    """One change overridden, one falls through to base policy."""
    p = tmp_path / "mixed.yaml"
    p.write_text(
        """
base_policy: strict_abi
overrides:
  enum_member_renamed: ignore
""".strip(),
        encoding="utf-8",
    )
    pf = PolicyFile.load(p)

    override_change = MagicMock()
    override_change.kind = ChangeKind.ENUM_MEMBER_RENAMED

    base_change = MagicMock()
    base_change.kind = ChangeKind.FUNC_REMOVED  # BREAKING in strict_abi

    # Mix: override says COMPATIBLE, base says BREAKING → BREAKING wins
    result = pf.compute_verdict([override_change, base_change])
    assert result == Verdict.BREAKING


def test_policy_file_describe_no_overrides(tmp_path: Path) -> None:
    """describe() formats correctly when overrides is empty (covers line 177 branch)."""
    p = tmp_path / "no_overrides.yaml"
    p.write_text("base_policy: strict_abi\n", encoding="utf-8")

    pf = PolicyFile.load(p)
    text = pf.describe()
    assert "base_policy: strict_abi" in text
    assert "overrides: (none)" in text


def test_policy_file_unknown_kind_logs_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    p = tmp_path / "unknown_kind.yaml"
    p.write_text(
        """
overrides:
  not_a_real_kind: ignore
""".strip(),
        encoding="utf-8",
    )

    with caplog.at_level("WARNING"):
        pf = PolicyFile.load(p)

    assert pf.overrides == {}
    assert "unknown ChangeKind slugs" in caplog.text


def test_policy_file_risk_severity_produces_compatible_with_risk(tmp_path: Path) -> None:
    """severity: risk in YAML policy file → COMPATIBLE_WITH_RISK verdict."""
    p = tmp_path / "policy.yaml"
    p.write_text(
        """
base_policy: strict_abi
overrides:
  func_added: risk
""".strip(),
        encoding="utf-8",
    )

    pf = PolicyFile.load(p)
    result = pf.compute_verdict([_change(ChangeKind.FUNC_ADDED)])
    assert result == Verdict.COMPATIBLE_WITH_RISK, (
        f"Expected COMPATIBLE_WITH_RISK for severity=risk override, got {result}"
    )


def test_policy_file_symbol_version_required_added_is_risk_by_default(tmp_path: Path) -> None:
    """SYMBOL_VERSION_REQUIRED_ADDED must produce COMPATIBLE_WITH_RISK with default policy."""
    p = tmp_path / "policy.yaml"
    p.write_text("base_policy: strict_abi", encoding="utf-8")

    pf = PolicyFile.load(p)
    result = pf.compute_verdict([_change(ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED)])
    assert result == Verdict.COMPATIBLE_WITH_RISK, (
        f"SYMBOL_VERSION_REQUIRED_ADDED must be COMPATIBLE_WITH_RISK, got {result}"
    )
