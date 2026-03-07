"""Integration tests for ABI check examples."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

# (case_dir_name, expected_verdict, header_v1, header_v2)
# header_v1/v2: relative to the case dir; None means use source file
CASES = [
    ("case01_symbol_removal",       "BREAKING",    "v1.c",      "v2.c"),
    ("case02_param_type_change",    "BREAKING",    "v1.c",      "v2.c"),
    ("case03_compat_addition",      "COMPATIBLE",  "v1.c",      "v2.c"),
    ("case04_no_change",            "NO_CHANGE",   "v1.c",      "v1.c"),
    ("case05_soname",               "COMPATIBLE",  "bad.c",     "good.c"),
    ("case06_visibility",           "COMPATIBLE",  "bad.c",     "good.c"),
    ("case07_struct_layout",        "BREAKING",    "v1.c",      "v2.c"),
    ("case08_enum_value_change",    "BREAKING",    "v1.c",      "v2.c"),
    ("case09_cpp_vtable",           "BREAKING",    "v1.cpp",    "v2.cpp"),
    ("case10_return_type",          "BREAKING",    "v1.c",      "v2.c"),
    ("case11_global_var_type",      "BREAKING",    "v1.c",      "v2.c"),
    ("case12_function_removed",     "BREAKING",    "v1.c",      "v2.c"),
    ("case13_symbol_versioning",    "COMPATIBLE",  "bad.c",     "good.c"),
    ("case14_cpp_class_size",       "BREAKING",    "v1.cpp",    "v2.cpp"),
    ("case15_noexcept_change",      "BREAKING",    "v1.cpp",    "v2.cpp"),
    ("case16_inline_to_non_inline", "COMPATIBLE",  "v1.hpp",    "v2.hpp"),
    ("case17_template_abi",         "BREAKING",    "v1.hpp",    "v2.hpp"),
    ("case18_dependency_leak",      "BREAKING",    "foo_v1.h",  "foo_v2.h"),
]


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        pytest.skip(f"{name} not found in PATH")


@pytest.mark.integration
@pytest.mark.parametrize("case_name,expected_verdict,hdr_v1,hdr_v2", CASES,
                         ids=[c[0] for c in CASES])
def test_abi_example(case_name, expected_verdict, hdr_v1, hdr_v2, tmp_path):
    _require_tool("castxml")
    _require_tool("gcc")
    _require_tool("g++")

    case_dir = EXAMPLES_DIR / case_name
    assert case_dir.is_dir(), f"Case directory not found: {case_dir}"

    # Copy case dir to tmp_path for isolated build (no artifacts in source tree)
    build_dir = tmp_path / case_name
    shutil.copytree(str(case_dir), str(build_dir))

    # Build libraries
    build = subprocess.run(
        ["make", "-C", str(build_dir)],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if build.returncode != 0:
        pytest.skip(f"make failed in {case_name}:\n{build.stderr[:500]}")

    libv1 = build_dir / "libv1.so"
    libv2 = build_dir / "libv2.so"
    assert libv1.exists(), f"libv1.so not built in {case_name}"
    assert libv2.exists(), f"libv2.so not built in {case_name}"

    snap1 = tmp_path / "snap1.json"
    snap2 = tmp_path / "snap2.json"

    header1 = build_dir / hdr_v1
    header2 = build_dir / hdr_v2

    # Dump v1
    r1 = subprocess.run(
        ["abicheck", "dump", str(libv1), "-H", str(header1), "-o", str(snap1)],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if r1.returncode != 0:
        pytest.fail(f"abicheck dump v1 failed in {case_name}:\n{r1.stderr[:500]}")

    # Dump v2
    r2 = subprocess.run(
        ["abicheck", "dump", str(libv2), "-H", str(header2), "-o", str(snap2)],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if r2.returncode != 0:
        pytest.fail(f"abicheck dump v2 failed in {case_name}:\n{r2.stderr[:500]}")

    # Compare
    rc = subprocess.run(
        ["abicheck", "compare", str(snap1), str(snap2), "--format", "json"],
        capture_output=True, text=True, check=False, timeout=60,
    )

    try:
        result = json.loads(rc.stdout)
        verdict = result.get("verdict", "")
    except json.JSONDecodeError:
        pytest.fail(
            f"abicheck compare produced invalid JSON for {case_name} "
            f"(returncode={rc.returncode}):\n{rc.stdout[:500]}"
        )

    assert verdict == expected_verdict, (
        f"{case_name}: expected verdict={expected_verdict!r}, got {verdict!r}\n"
        f"stdout: {rc.stdout[:1000]}"
    )
