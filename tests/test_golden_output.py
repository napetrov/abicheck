"""Golden regression tests for CLI 'compare' command output.

Compares the markdown output of abicheck compare against known-good
golden files stored in tests/golden/.

Usage:
  # Run golden tests:
  pytest tests/test_golden_output.py

  # Update golden files after intentional output changes:
  pytest tests/test_golden_output.py --update-goldens
"""
from __future__ import annotations

from pathlib import Path

import pytest

from abicheck.checker import compare
from abicheck.model import (
    AbiSnapshot,
    EnumMember,
    EnumType,
    Function,
    RecordType,
    TypeField,
    Visibility,
)
from abicheck.reporter import to_markdown

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
TESTS_DIR = Path(__file__).parent
GOLDEN_DIR = TESTS_DIR / "golden"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snap(ver: str = "1.0", funcs=None, types=None, enums=None) -> AbiSnapshot:
    s = AbiSnapshot(library="libfoo.so", version=ver)
    s.functions = funcs or []
    s.types = types or []
    s.enums = enums or []
    return s


def _fn(name: str, mangled: str, ret: str = "int") -> Function:
    return Function(name=name, mangled=mangled, return_type=ret, visibility=Visibility.PUBLIC)


def _run_golden(
    case_id: str,
    old: AbiSnapshot,
    new: AbiSnapshot,
    update: bool,
) -> None:
    """Run one golden comparison: either update or verify."""
    golden_path = GOLDEN_DIR / f"{case_id}.md"
    result = compare(old, new)
    actual = to_markdown(result)

    if update:
        GOLDEN_DIR.mkdir(exist_ok=True)
        golden_path.write_text(actual, encoding="utf-8")
        pytest.skip(f"Updated golden: {golden_path.name}")
        return

    if not golden_path.exists():
        pytest.fail(
            f"Golden file missing: {golden_path}\n"
            f"Run with --update-goldens to create it.\n"
            f"Current output:\n{actual}"
        )

    expected = golden_path.read_text(encoding="utf-8")
    if actual != expected:
        diff_lines: list[str] = []
        exp_lines = expected.splitlines()
        act_lines = actual.splitlines()
        for i, (e, a) in enumerate(zip(exp_lines, act_lines)):
            if e != a:
                diff_lines.append(f"  Line {i+1}:\n    expected: {e!r}\n    actual:   {a!r}")
        if len(exp_lines) != len(act_lines):
            diff_lines.append(
                f"  Length: expected {len(exp_lines)} lines, got {len(act_lines)}"
            )
        pytest.fail(
            f"Golden mismatch for {case_id}:\n" + "\n".join(diff_lines[:10])
        )


# ---------------------------------------------------------------------------
# Golden test cases
# ---------------------------------------------------------------------------

@pytest.mark.golden
def test_golden_no_change(update_goldens: bool) -> None:
    """Identical snapshots → NO_CHANGE output is stable."""
    old = _snap(ver="1.0", funcs=[_fn("compute", "_Z7computei")])
    new = _snap(ver="2.0", funcs=[_fn("compute", "_Z7computei")])
    _run_golden("no_change", old, new, update_goldens)


@pytest.mark.golden
def test_golden_func_removed(update_goldens: bool) -> None:
    """Public function removal → BREAKING output is stable."""
    old = _snap(ver="1.0", funcs=[_fn("compute", "_Z7computei"), _fn("helper", "_Z6helperi")])
    new = _snap(ver="2.0", funcs=[_fn("compute", "_Z7computei")])
    _run_golden("func_removed", old, new, update_goldens)


@pytest.mark.golden
def test_golden_struct_size_change(update_goldens: bool) -> None:
    """Struct with new field → BREAKING size-change output is stable."""
    old = _snap(ver="1.0", types=[RecordType(
        name="Point", kind="struct", size_bits=64,
        fields=[TypeField("x", "int", 0), TypeField("y", "int", 32)],
    )])
    new = _snap(ver="2.0", types=[RecordType(
        name="Point", kind="struct", size_bits=96,
        fields=[TypeField("x", "int", 0), TypeField("y", "int", 32), TypeField("z", "int", 64)],
    )])
    _run_golden("struct_size_change", old, new, update_goldens)


@pytest.mark.golden
def test_golden_enum_change(update_goldens: bool) -> None:
    """Enum member value change → BREAKING output is stable."""
    old = _snap(ver="1.0", enums=[EnumType(
        name="Color",
        members=[EnumMember("RED", 0), EnumMember("GREEN", 1), EnumMember("BLUE", 2)],
    )])
    new = _snap(ver="2.0", enums=[EnumType(
        name="Color",
        members=[EnumMember("RED", 0), EnumMember("GREEN", 5), EnumMember("BLUE", 2)],
    )])
    _run_golden("enum_change", old, new, update_goldens)


@pytest.mark.golden
def test_golden_compatible_addition(update_goldens: bool) -> None:
    """New public function → COMPATIBLE output is stable."""
    old = _snap(ver="1.0", funcs=[_fn("compute", "_Z7computei")])
    new = _snap(ver="2.0", funcs=[_fn("compute", "_Z7computei"), _fn("helper", "_Z6helperi")])
    _run_golden("compatible_addition", old, new, update_goldens)
