"""tests/test_validate_examples_unit.py

Unit tests for the validate_examples.py CLI harness (PR #63).
Does NOT require a full compile/run of examples — tests harness logic only.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import importlib

# Load module under test
sys.path.insert(0, str(Path(__file__).parent.parent))
from tests.validate_examples import (
    main,
    _find_sources,
    _normalize_verdict,
    CaseResult,
)


# ---------------------------------------------------------------------------
# _normalize_verdict — SOURCE_BREAK must NOT collapse to COMPATIBLE
# ---------------------------------------------------------------------------

def test_normalize_verdict_preserves_source_break():
    assert _normalize_verdict("SOURCE_BREAK") == "SOURCE_BREAK"


def test_normalize_verdict_preserves_compatible():
    assert _normalize_verdict("COMPATIBLE") == "COMPATIBLE"


def test_normalize_verdict_preserves_breaking():
    assert _normalize_verdict("BREAKING") == "BREAKING"


def test_normalize_verdict_preserves_no_change():
    assert _normalize_verdict("NO_CHANGE") == "NO_CHANGE"


# ---------------------------------------------------------------------------
# ground_truth.json structural integrity
# ---------------------------------------------------------------------------

GROUND_TRUTH = Path(__file__).parent.parent / "examples" / "ground_truth.json"
VALID_CATEGORIES = {"breaking", "compatible", "bad_practice", "source_break"}
VALID_VERDICTS   = {"BREAKING", "COMPATIBLE", "NO_CHANGE", "SOURCE_BREAK"}


def test_ground_truth_has_41_cases():
    j = json.loads(GROUND_TRUTH.read_text())
    assert len(j["verdicts"]) == 41, f"Expected 41 cases, got {len(j['verdicts'])}"


def test_ground_truth_all_entries_have_category():
    j = json.loads(GROUND_TRUTH.read_text())
    missing = [k for k, v in j["verdicts"].items() if "category" not in v]
    assert not missing, f"Missing 'category' in: {missing}"


def test_ground_truth_categories_are_valid():
    j = json.loads(GROUND_TRUTH.read_text())
    invalid = {k: v["category"] for k, v in j["verdicts"].items()
               if v.get("category") not in VALID_CATEGORIES}
    assert not invalid, f"Invalid categories: {invalid}"


def test_ground_truth_verdicts_are_valid():
    j = json.loads(GROUND_TRUTH.read_text())
    invalid = {k: v["expected"] for k, v in j["verdicts"].items()
               if v.get("expected") not in VALID_VERDICTS and v.get("expected") is not None}
    assert not invalid, f"Invalid expected verdicts: {invalid}"


# ---------------------------------------------------------------------------
# CLI: --category filter
# ---------------------------------------------------------------------------

def test_main_category_filter_json(tmp_path, monkeypatch):
    """--category filter must restrict processed cases to matching category."""
    gt = {
        "version": "1",
        "description": "",
        "verdicts": {
            "case_breaking": {"expected": "BREAKING", "category": "breaking"},
            "case_compatible": {"expected": "COMPATIBLE", "category": "compatible"},
        }
    }
    gt_file = tmp_path / "ground_truth.json"
    gt_file.write_text(json.dumps(gt))

    import tests.validate_examples as ve
    import shutil as real_shutil
    monkeypatch.setattr(ve, "GROUND_TRUTH", gt_file)
    monkeypatch.setattr(ve, "EXAMPLES_DIR", tmp_path)
    monkeypatch.setattr(real_shutil, "which", lambda t: "/usr/bin/" + t)

    captured_names: list[str] = []

    def capturing_run(name, entry, tmp_base, fail_fast=False):
        captured_names.append(name)
        return CaseResult(name, "PASS", entry.get("expected"), entry.get("expected"), "")

    with patch.object(ve, "run_case", side_effect=capturing_run):
        main(["--category", "breaking", "--json"])

    assert "case_breaking" in captured_names
    assert "case_compatible" not in captured_names, "compatible case must be filtered out"


# ---------------------------------------------------------------------------
# CLI: --json exit code
# ---------------------------------------------------------------------------

def test_main_exits_0_when_all_pass(tmp_path, monkeypatch, capsys):
    gt = {"version": "1", "description": "", "verdicts": {
        "case01": {"expected": "BREAKING", "category": "breaking"},
    }}
    gt_file = tmp_path / "ground_truth.json"
    gt_file.write_text(json.dumps(gt))

    import tests.validate_examples as ve
    monkeypatch.setattr(ve, "GROUND_TRUTH", gt_file)
    monkeypatch.setattr(ve, "EXAMPLES_DIR", tmp_path)
    monkeypatch.setattr("shutil.which", lambda t: "/usr/bin/" + t)

    with patch.object(ve, "run_case", return_value=CaseResult("case01", "PASS", "BREAKING", "BREAKING", "")):
        rc = main(["--json"])
    assert rc == 0


def test_main_exits_1_on_fail(tmp_path, monkeypatch, capsys):
    gt = {"version": "1", "description": "", "verdicts": {
        "case01": {"expected": "BREAKING", "category": "breaking"},
    }}
    gt_file = tmp_path / "ground_truth.json"
    gt_file.write_text(json.dumps(gt))

    import tests.validate_examples as ve
    monkeypatch.setattr(ve, "GROUND_TRUTH", gt_file)
    monkeypatch.setattr(ve, "EXAMPLES_DIR", tmp_path)
    monkeypatch.setattr("shutil.which", lambda t: "/usr/bin/" + t)

    with patch.object(ve, "run_case", return_value=CaseResult("case01", "FAIL", "BREAKING", "COMPATIBLE", "mismatch")):
        rc = main(["--json"])
    assert rc == 1


def test_main_exits_2_when_tool_missing(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda t: None)
    rc = main(["--json"])
    assert rc == 2
