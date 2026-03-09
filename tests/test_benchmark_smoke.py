"""Smoke tests for scripts/benchmark_comparison.py.

Verifies that the benchmark script imports cleanly, parses args correctly,
and that the run_abicc_dumper / run_abicc_xml helpers handle missing tools
gracefully (return SKIP instead of crashing).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _load_benchmark():
    """Dynamically import scripts/benchmark_comparison.py."""
    mod_name = "benchmark_comparison"
    # Unload any cached version to ensure a fresh import
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(
        mod_name,
        SCRIPTS_DIR / "benchmark_comparison.py",
    )
    mod = importlib.util.module_from_spec(spec)
    # Must register in sys.modules BEFORE exec so @dataclass can resolve the module
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Import / parse_args ───────────────────────────────────────────────────────

def test_import_benchmark_script():
    """Script must import without errors."""
    mod = _load_benchmark()
    assert hasattr(mod, "main")
    assert hasattr(mod, "run_abicc_dumper")
    assert hasattr(mod, "run_abicc_xml")


def test_parse_args_defaults():
    mod = _load_benchmark()
    with patch("sys.argv", ["benchmark_comparison.py"]):
        args = mod.parse_args()
    assert args.abicc_timeout == mod.DEFAULT_ABICC_TIMEOUT
    assert args.abicc_mode == "both"
    assert not args.skip_abicc


def test_parse_args_custom_timeout():
    mod = _load_benchmark()
    with patch("sys.argv", ["benchmark_comparison.py", "--abicc-timeout", "60"]):
        args = mod.parse_args()
    assert args.abicc_timeout == 60


def test_parse_args_skip_abicc():
    mod = _load_benchmark()
    with patch("sys.argv", ["benchmark_comparison.py", "--skip-abicc"]):
        args = mod.parse_args()
    assert args.skip_abicc


def test_parse_args_abicc_mode_xml():
    mod = _load_benchmark()
    with patch("sys.argv", ["benchmark_comparison.py", "--abicc-mode", "xml"]):
        args = mod.parse_args()
    assert args.abicc_mode == "xml"


# ── Graceful SKIP when tool not present ──────────────────────────────────────

def test_run_abicc_dumper_skip_when_missing(tmp_path):
    """run_abicc_dumper returns SKIP if abi-dumper is not installed."""
    mod = _load_benchmark()
    dummy = tmp_path / "lib.so"
    dummy.touch()
    dummy_h = tmp_path / "v1.h"

    with patch("shutil.which", return_value=None):
        result = mod.run_abicc_dumper(dummy, dummy, dummy_h, dummy_h,
                                      "smoke_case", tmp_path)
    assert result.verdict == "SKIP"


def test_run_abicc_xml_skip_when_missing(tmp_path):
    """run_abicc_xml returns SKIP if abi-compliance-checker is not installed."""
    mod = _load_benchmark()
    dummy = tmp_path / "lib.so"
    dummy.touch()
    dummy_h = tmp_path / "v1.h"

    with patch("shutil.which", return_value=None):
        result = mod.run_abicc_xml(dummy, dummy, dummy_h, dummy_h,
                                   "smoke_case", tmp_path)
    assert result.verdict == "SKIP"


def test_run_abicheck_skip_when_missing(tmp_path):
    """run_abicheck returns SKIP if abicheck is not installed."""
    mod = _load_benchmark()
    dummy = tmp_path / "lib.so"
    dummy.touch()
    dummy_h = tmp_path / "v1.h"

    with patch("shutil.which", return_value=None):
        result = mod.run_abicheck(dummy, dummy, dummy_h, dummy_h,
                                  "smoke_case", tmp_path)
    assert result.verdict == "SKIP"


def test_run_abidiff_skip_when_missing(tmp_path):
    """run_abidiff returns SKIP if abidiff is not installed."""
    mod = _load_benchmark()
    dummy = tmp_path / "lib.so"
    dummy.touch()

    with patch("shutil.which", return_value=None):
        result = mod.run_abidiff(dummy, dummy, "smoke_case", tmp_path)
    assert result.verdict == "SKIP"


# ── ToolResult dataclass ──────────────────────────────────────────────────────

def test_tool_result_defaults():
    mod = _load_benchmark()
    r = mod.ToolResult(verdict="NO_CHANGE")
    assert r.verdict == "NO_CHANGE"
    assert r.changes == []
    assert r.raw_output == ""
    assert r.report_path == ""
