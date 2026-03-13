"""Follow-up tests for PR #100 (FRAME_REGISTER_CHANGED) and PR #101 (--policy CLI).

Covers:
- _extract_cfa_reg_from_fde helper behavior (including epilogue edge case)
- _normalize_arch, _build_addr_to_sym, _get_cfi_source helpers
- policy-aware compute_verdict: sdk_vendor, plugin_abi
- CLI/report filtering honoring --policy
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from abicheck.checker import DiffResult
from abicheck.checker_policy import (
    PLUGIN_ABI_DOWNGRADED_KINDS,
    SDK_VENDOR_COMPAT_KINDS,
    SDK_VENDOR_DOWNGRADED_KINDS,
    ChangeKind,
    Verdict,
    compute_verdict,
)
from abicheck.dwarf_advanced import (
    _build_addr_to_sym,
    _extract_cfa_reg_from_fde,
    _get_cfi_source,
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


def _make_symbol(name: str, value: int, bind: str) -> MagicMock:
    sym = MagicMock()
    sym.name = name
    sym.entry.st_value = value
    sym.entry.st_info.bind = bind
    return sym


def _make_section(symbols: list[MagicMock]) -> MagicMock:
    sect = MagicMock()
    sect.iter_symbols.return_value = symbols
    return sect


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


class TestBuildAddrToSym:
    def test_dynsym_precedence_same_address(self) -> None:
        elf = MagicMock()
        dyn = _make_section([_make_symbol("exported", 0x1000, "STB_GLOBAL")])
        sym = _make_section([_make_symbol("local_shadow", 0x1000, "STB_GLOBAL")])
        elf.get_section_by_name.side_effect = lambda name: {".dynsym": dyn, ".symtab": sym}.get(name)

        out = _build_addr_to_sym(elf)
        assert out[0x1000] == "exported"

    def test_ignores_local_and_zero(self) -> None:
        elf = MagicMock()
        dyn = _make_section([
            _make_symbol("zero", 0, "STB_GLOBAL"),
            _make_symbol("local", 0x2000, "STB_LOCAL"),
            _make_symbol("weak_ok", 0x3000, "STB_WEAK"),
        ])
        elf.get_section_by_name.side_effect = lambda name: {".dynsym": dyn, ".symtab": None}.get(name)

        out = _build_addr_to_sym(elf)
        assert 0x2000 not in out
        assert 0 not in out
        assert out[0x3000] == "weak_ok"


class TestGetCfiSource:
    def test_prefers_eh_frame(self) -> None:
        dwarf = MagicMock()
        eh_entries = [object()]
        dwarf.get_EH_CFI_entries.return_value = eh_entries
        assert _get_cfi_source(dwarf) is eh_entries

    def test_fallbacks_to_debug_frame(self) -> None:
        dwarf = MagicMock()
        dbg_entries = [object(), object()]
        dwarf.get_EH_CFI_entries.return_value = None
        dwarf.get_CFI_entries.return_value = dbg_entries
        assert _get_cfi_source(dwarf) is dbg_entries

    def test_returns_none_on_missing_both(self) -> None:
        dwarf = MagicMock()
        dwarf.get_EH_CFI_entries.side_effect = AttributeError("no eh")
        dwarf.get_CFI_entries.side_effect = AttributeError("no dbg")
        assert _get_cfi_source(dwarf) is None


# ── _extract_cfa_reg_from_fde ─────────────────────────────────────────────────

class TestExtractCfaRegFromFde:

    def test_tie_break_by_highest_pc(self) -> None:
        """2-row table: entry rbp, body rsp -> tie => higher PC row wins (rsp)."""
        cfa_entry = MagicMock()
        cfa_entry.reg = 6   # rbp — entry-state (lower PC)
        cfa_post = MagicMock()
        cfa_post.reg = 7    # rsp — post-prologue (higher PC)

        rows = [
            {"pc": 0x1000, "cfa": cfa_entry},
            {"pc": 0x1010, "cfa": cfa_post},
        ]
        assert _extract_cfa_reg_from_fde(_make_fde(rows), "x64") == "rsp"

    def test_modal_register_avoids_epilogue_bias(self) -> None:
        """3-row table: entry/body rbp, epilogue rsp -> dominant should be rbp."""
        cfa_entry = MagicMock(); cfa_entry.reg = 6   # rbp
        cfa_body = MagicMock(); cfa_body.reg = 6    # rbp
        cfa_epi = MagicMock(); cfa_epi.reg = 7      # rsp

        rows = [
            {"pc": 0x1000, "cfa": cfa_entry},
            {"pc": 0x1010, "cfa": cfa_body},
            {"pc": 0x1020, "cfa": cfa_epi},
        ]
        assert _extract_cfa_reg_from_fde(_make_fde(rows), "x64") == "rbp"

    def test_single_row_used(self) -> None:
        cfa = MagicMock()
        cfa.reg = 6
        assert _extract_cfa_reg_from_fde(_make_fde([{"pc": 0x1000, "cfa": cfa}]), "x64") == "rbp"

    def test_empty_table_returns_none(self) -> None:
        assert _extract_cfa_reg_from_fde(_make_fde([]), "x64") is None

    def test_no_cfa_key_returns_none(self) -> None:
        assert _extract_cfa_reg_from_fde(_make_fde([{"pc": 0x1000}]), "x64") is None

    def test_cfa_no_reg_attr_returns_none(self) -> None:
        cfa = MagicMock(spec=[])
        assert _extract_cfa_reg_from_fde(_make_fde([{"pc": 0x1000, "cfa": cfa}]), "x64") is None

    def test_decode_exception_returns_none(self) -> None:
        fde = MagicMock()
        fde.get_decoded.side_effect = ValueError("parse error")
        assert _extract_cfa_reg_from_fde(fde, "x64") is None


# ── compute_verdict — sdk_vendor ──────────────────────────────────────────────

class TestSdkVendorVerdict:
    """sdk_vendor downgrades source-level API_BREAK kinds to COMPATIBLE."""

    def test_alias_kept_for_backward_compat(self) -> None:
        assert SDK_VENDOR_DOWNGRADED_KINDS == SDK_VENDOR_COMPAT_KINDS

    def test_enum_member_renamed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.ENUM_MEMBER_RENAMED)], policy="sdk_vendor") == Verdict.COMPATIBLE

    def test_field_renamed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.FIELD_RENAMED)], policy="sdk_vendor") == Verdict.COMPATIBLE

    def test_source_level_kind_changed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.SOURCE_LEVEL_KIND_CHANGED)], policy="sdk_vendor") == Verdict.COMPATIBLE

    def test_default_value_changed_strict_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.PARAM_DEFAULT_VALUE_CHANGED)], policy="strict_abi") == Verdict.COMPATIBLE

    def test_func_removed_still_breaking(self) -> None:
        assert compute_verdict([_change(ChangeKind.FUNC_REMOVED)], policy="sdk_vendor") == Verdict.BREAKING

    def test_strict_abi_enum_rename_is_api_break(self) -> None:
        assert compute_verdict([_change(ChangeKind.ENUM_MEMBER_RENAMED)], policy="strict_abi") == Verdict.API_BREAK

    def test_all_sdk_compat_kinds_produce_compatible(self) -> None:
        for kind in SDK_VENDOR_COMPAT_KINDS:
            result = compute_verdict([_change(kind)], policy="sdk_vendor")
            assert result == Verdict.COMPATIBLE, (
                f"{kind} with sdk_vendor → {result!r}, expected COMPATIBLE"
            )


# ── compute_verdict — plugin_abi ──────────────────────────────────────────────

class TestPluginAbiVerdict:
    """plugin_abi downgrades calling-convention kinds to COMPATIBLE."""

    def test_calling_convention_changed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.CALLING_CONVENTION_CHANGED)], policy="plugin_abi") == Verdict.COMPATIBLE

    def test_value_abi_trait_changed_is_compatible(self) -> None:
        assert compute_verdict([_change(ChangeKind.VALUE_ABI_TRAIT_CHANGED)], policy="plugin_abi") == Verdict.COMPATIBLE

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


# ── CLI/report-filter policy integration ─────────────────────────────────────

class TestCliPolicyFiltering:
    def _mk_result(self, *kinds: ChangeKind) -> DiffResult:
        return DiffResult(
            old_version="1.0",
            new_version="2.0",
            library="lib.so",
            changes=[_change(k) for k in kinds],
            verdict=Verdict.NO_CHANGE,
        )

    def test_filter_source_only_honors_policy(self) -> None:
        from abicheck.cli import _filter_source_only

        result = self._mk_result(ChangeKind.ENUM_MEMBER_RENAMED)
        strict = _filter_source_only(result, policy="strict_abi")
        sdk = _filter_source_only(result, policy="sdk_vendor")

        assert strict.verdict == Verdict.API_BREAK
        assert sdk.verdict == Verdict.COMPATIBLE

    def test_filter_binary_only_honors_policy(self) -> None:
        from abicheck.cli import _filter_binary_only

        result = self._mk_result(ChangeKind.CALLING_CONVENTION_CHANGED)
        strict = _filter_binary_only(result, policy="strict_abi")
        plugin = _filter_binary_only(result, policy="plugin_abi")

        assert strict.verdict == Verdict.BREAKING
        assert plugin.verdict == Verdict.COMPATIBLE


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

    def test_policy_forwarded_to_compare(self, tmp_path: Any) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main

        old_p, new_p = self._write_snapshots(tmp_path)

        def _fake_compare(*_args: Any, **kwargs: Any) -> DiffResult:
            assert kwargs["policy"] == "plugin_abi"
            return DiffResult(old_version="1.0", new_version="2.0", library="lib.so", changes=[], verdict=Verdict.NO_CHANGE)

        with patch("abicheck.cli.compare", side_effect=_fake_compare):
            result = CliRunner().invoke(main, ["compare", str(old_p), str(new_p), "--policy", "plugin_abi"])

        assert result.exit_code == 0, result.output

    def test_policy_invalid_case_rejected(self, tmp_path: Any) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main
        old_p, new_p = self._write_snapshots(tmp_path)
        result = CliRunner().invoke(main, ["compare", str(old_p), str(new_p), "--policy", "SDK_VENDOR"])
        assert result.exit_code == 2

    def test_policy_file_forwarded_to_compare(self, tmp_path: Any) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main

        old_p, new_p = self._write_snapshots(tmp_path)
        policy_p = tmp_path / "policy.yaml"
        policy_p.write_text("overrides: {}\n", encoding="utf-8")

        def _fake_compare(*_args: Any, **kwargs: Any) -> DiffResult:
            assert kwargs["policy_file"] is not None
            return DiffResult(old_version="1.0", new_version="2.0", library="lib.so", changes=[], verdict=Verdict.NO_CHANGE)

        with patch("abicheck.cli.compare", side_effect=_fake_compare):
            result = CliRunner().invoke(
                main,
                ["compare", str(old_p), str(new_p), "--policy-file", str(policy_p)],
            )

        assert result.exit_code == 0, result.output

    def test_help_lists_policy_choices(self) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main
        result = CliRunner().invoke(main, ["compare", "--help"])
        assert "sdk_vendor" in result.output
        assert "plugin_abi" in result.output
        assert "strict_abi" in result.output
        assert "--policy-file" in result.output


class TestCompatPolicyExposure:
    def test_compat_help_has_no_policy_flag(self) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main
        result = CliRunner().invoke(main, ["compat", "--help"])
        assert result.exit_code == 0, result.output
        assert "--policy" not in result.output
