"""Follow-up tests for PR #100 (FRAME_REGISTER_CHANGED) and PR #101 (--policy CLI).

Addresses all review findings:
- _extract_cfa_reg_from_fde helper with mock FDE objects (post-prologue row selection)
- _normalize_arch helper
- policy-aware compute_verdict: sdk_vendor, plugin_abi
- CLI --policy flag end-to-end via CliRunner
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from abicheck.checker_policy import (
    PLUGIN_ABI_DOWNGRADED_KINDS,
    SDK_VENDOR_COMPAT_KINDS,
    ChangeKind,
    Verdict,
    compute_verdict,
)
from abicheck.dwarf_advanced import (
    _extract_cfa_reg_from_fde,
    _normalize_arch,
    _reg_name,
)
from abicheck.model import AbiSnapshot

# ── helpers ──────────────────────────────────────────────────────────────────

def _change(kind: ChangeKind) -> Any:
    c = MagicMock()
    c.kind = kind
    return c


def _make_fde(rows: list[dict[str, Any]]) -> MagicMock:
    decoded = MagicMock()
    decoded.table = rows
    fde = MagicMock()
    fde.get_decoded.return_value = decoded
    return fde


# ── _reg_name helpers ─────────────────────────────────────────────────────────

class TestRegNameHelpers:
    def test_x86_64_rbp(self) -> None:
        assert _reg_name(6, "x64") == "rbp"

    def test_x86_64_rsp(self) -> None:
        assert _reg_name(7, "x64") == "rsp"

    def test_x86_ebp(self) -> None:
        assert _reg_name(5, "x86") == "ebp"

    def test_aarch64_sp(self) -> None:
        assert _reg_name(31, "aarch64") == "sp"

    def test_unknown_arch_fallback(self) -> None:
        assert _reg_name(7, "mips") == "reg7"

    def test_unknown_regnum_fallback(self) -> None:
        assert _reg_name(99, "x64") == "reg99"


class TestNormalizeArch:
    def test_x64(self) -> None:
        elf = MagicMock()
        elf.get_machine_arch.return_value = "x64"
        assert _normalize_arch(elf) == "x64"

    def test_aarch64(self) -> None:
        elf = MagicMock()
        elf.get_machine_arch.return_value = "AArch64"
        assert _normalize_arch(elf) == "aarch64"

    def test_unknown_passthrough(self) -> None:
        elf = MagicMock()
        elf.get_machine_arch.return_value = "riscv"
        assert _normalize_arch(elf) == "riscv"


# ── _extract_cfa_reg_from_fde ─────────────────────────────────────────────────

class TestExtractCfaRegFromFde:

    def test_picks_highest_pc_row_not_first(self) -> None:
        """Must pick post-prologue (highest-PC) row, not entry-state row."""
        cfa_entry = MagicMock()
        cfa_entry.reg = 6   # rbp — entry-state (lower PC)
        cfa_post = MagicMock()
        cfa_post.reg = 7    # rsp — post-prologue (higher PC)

        rows = [
            {"pc": 0x1000, "cfa": cfa_entry},   # entry: rbp
            {"pc": 0x1010, "cfa": cfa_post},     # post-prologue: rsp ← should win
        ]
        assert _extract_cfa_reg_from_fde(_make_fde(rows), "x64") == "rsp"

    def test_single_row_used(self) -> None:
        cfa = MagicMock()
        cfa.reg = 6   # rbp
        assert _extract_cfa_reg_from_fde(_make_fde([{"pc": 0x1000, "cfa": cfa}]), "x64") == "rbp"

    def test_empty_table_returns_none(self) -> None:
        assert _extract_cfa_reg_from_fde(_make_fde([]), "x64") is None

    def test_no_cfa_key_returns_none(self) -> None:
        assert _extract_cfa_reg_from_fde(_make_fde([{"pc": 0x1000}]), "x64") is None

    def test_cfa_no_reg_attr_returns_none(self) -> None:
        cfa = MagicMock(spec=[])  # no .reg
        assert _extract_cfa_reg_from_fde(_make_fde([{"pc": 0x1000, "cfa": cfa}]), "x64") is None

    def test_decode_exception_returns_none(self) -> None:
        fde = MagicMock()
        fde.get_decoded.side_effect = ValueError("parse error")
        assert _extract_cfa_reg_from_fde(fde, "x64") is None


# ── compute_verdict — sdk_vendor ──────────────────────────────────────────────

class TestSdkVendorVerdict:
    """sdk_vendor downgrades source-level API_BREAK kinds to COMPATIBLE."""

    def test_enum_member_renamed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.ENUM_MEMBER_RENAMED)], policy="sdk_vendor") == Verdict.COMPATIBLE

    def test_field_renamed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.FIELD_RENAMED)], policy="sdk_vendor") == Verdict.COMPATIBLE

    def test_param_renamed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.PARAM_RENAMED)], policy="sdk_vendor") == Verdict.COMPATIBLE

    def test_method_access_changed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.METHOD_ACCESS_CHANGED)], policy="sdk_vendor") == Verdict.COMPATIBLE

    def test_source_level_kind_changed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.SOURCE_LEVEL_KIND_CHANGED)], policy="sdk_vendor") == Verdict.COMPATIBLE

    def test_func_removed_still_breaking(self) -> None:
        assert compute_verdict([_change(ChangeKind.FUNC_REMOVED)], policy="sdk_vendor") == Verdict.BREAKING

    def test_strict_abi_enum_rename_is_api_break(self) -> None:
        """Verify strict_abi baseline: enum rename → API_BREAK (not COMPATIBLE)."""
        assert compute_verdict([_change(ChangeKind.ENUM_MEMBER_RENAMED)], policy="strict_abi") == Verdict.API_BREAK

    def test_all_sdk_compat_kinds_produce_compatible(self) -> None:
        for kind in SDK_VENDOR_COMPAT_KINDS:
            result = compute_verdict([_change(kind)], policy="sdk_vendor")
            assert result == Verdict.COMPATIBLE, (
                f"{kind} with sdk_vendor → {result!r}, expected COMPATIBLE"
            )

    def test_mixed_breaking_and_compat_yields_breaking(self) -> None:
        changes = [_change(ChangeKind.FIELD_RENAMED), _change(ChangeKind.FUNC_REMOVED)]
        assert compute_verdict(changes, policy="sdk_vendor") == Verdict.BREAKING


# ── compute_verdict — plugin_abi ──────────────────────────────────────────────

class TestPluginAbiVerdict:
    """plugin_abi downgrades calling-convention kinds to COMPATIBLE."""

    def test_calling_convention_changed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.CALLING_CONVENTION_CHANGED)], policy="plugin_abi") == Verdict.COMPATIBLE

    def test_calling_convention_strict_is_breaking(self) -> None:
        assert compute_verdict([_change(ChangeKind.CALLING_CONVENTION_CHANGED)], policy="strict_abi") == Verdict.BREAKING

    def test_func_removed_still_breaking_in_plugin(self) -> None:
        assert compute_verdict([_change(ChangeKind.FUNC_REMOVED)], policy="plugin_abi") == Verdict.BREAKING

    def test_all_plugin_downgraded_kinds_produce_compatible(self) -> None:
        for kind in PLUGIN_ABI_DOWNGRADED_KINDS:
            result = compute_verdict([_change(kind)], policy="plugin_abi")
            assert result == Verdict.COMPATIBLE, (
                f"{kind} with plugin_abi → {result!r}, expected COMPATIBLE"
            )

    def test_unknown_policy_fallback_to_strict(self) -> None:
        changes = [_change(ChangeKind.CALLING_CONVENTION_CHANGED)]
        assert compute_verdict(changes, policy="nonexistent") == Verdict.BREAKING


# ── CLI --policy end-to-end ───────────────────────────────────────────────────

class TestCliPolicy:

    def _write_snapshots(self, tmp_path: Any) -> tuple[Any, Any]:
        from abicheck.serialization import snapshot_to_dict

        old = AbiSnapshot(library="lib.so", version="1.0")
        new = AbiSnapshot(library="lib.so", version="2.0")
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        old_p.write_text(json.dumps(snapshot_to_dict(old)))
        new_p.write_text(json.dumps(snapshot_to_dict(new)))
        return old_p, new_p

    def test_policy_strict_abi_accepted(self, tmp_path: Any) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main
        old_p, new_p = self._write_snapshots(tmp_path)
        result = CliRunner().invoke(main, ["compare", str(old_p), str(new_p), "--policy", "strict_abi"])
        assert result.exit_code in (0, 2, 4), result.output

    def test_policy_sdk_vendor_accepted(self, tmp_path: Any) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main
        old_p, new_p = self._write_snapshots(tmp_path)
        result = CliRunner().invoke(main, ["compare", str(old_p), str(new_p), "--policy", "sdk_vendor"])
        assert result.exit_code in (0, 2, 4), result.output

    def test_policy_plugin_abi_accepted(self, tmp_path: Any) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main
        old_p, new_p = self._write_snapshots(tmp_path)
        result = CliRunner().invoke(main, ["compare", str(old_p), str(new_p), "--policy", "plugin_abi"])
        assert result.exit_code in (0, 2, 4), result.output

    def test_policy_invalid_rejected(self, tmp_path: Any) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main
        old_p, new_p = self._write_snapshots(tmp_path)
        result = CliRunner().invoke(main, ["compare", str(old_p), str(new_p), "--policy", "bad_policy"])
        assert result.exit_code == 2

    def test_help_lists_policy_choices(self) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main
        result = CliRunner().invoke(main, ["compare", "--help"])
        assert "sdk_vendor" in result.output
        assert "plugin_abi" in result.output
        assert "strict_abi" in result.output
