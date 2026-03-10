"""Integration tests for ABI check examples."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

# (case_dir_name, expected_verdict, header_v1, header_v2)
#
# Expected verdicts reflect what abicheck currently detects with castxml+ELF analysis:
#   ✅ DETECTED  — abicheck catches the break reliably
#   ⚠️  LIMITATION — break exists but abicheck cannot detect it yet (documented gap)
#   📋 POLICY   — not a binary break; SONAME/versioning are policy issues
#
CASES = [
    # ✅ Symbol removed from ELF dynsym → FUNC_REMOVED → BREAKING
    ("case01_symbol_removal", "BREAKING", "v1.c", "v2.c"),
    # ✅ Parameter type change visible via castxml → FUNC_PARAMS_CHANGED → BREAKING
    ("case02_param_type_change", "BREAKING", "v1.c", "v2.c"),
    # ✅ New symbol added → FUNC_ADDED → COMPATIBLE
    ("case03_compat_addition", "COMPATIBLE", "v1.c", "v2.c"),
    # ✅ Identical libs → NO_CHANGE
    ("case04_no_change", "NO_CHANGE", "v1.c", "v1.c"),
    # 📋 SONAME is a policy attribute, not tracked by checker → NO_CHANGE
    ("case05_soname", "COMPATIBLE", "bad.c", "good.c"),
    # ✅ internal_helper/another_impl hidden in good.c → removed from dynsym → BREAKING
    ("case06_visibility", "BREAKING", "bad.c", "good.c"),
    # ✅ Struct size change detected via castxml → TYPE_SIZE_CHANGED → BREAKING
    ("case07_struct_layout", "BREAKING", "v1.c", "v2.c"),
    # ✅ Enum member value changes detected via _diff_enums() → BREAKING
    ("case08_enum_value_change", "BREAKING", "v1.c", "v2.c"),
    # ✅ vtable reorder/change detected → TYPE_VTABLE_CHANGED → BREAKING
    ("case09_cpp_vtable", "BREAKING", "v1.cpp", "v2.cpp"),
    # ✅ Return type change detected via castxml → FUNC_RETURN_CHANGED → BREAKING
    ("case10_return_type", "BREAKING", "v1.c", "v2.c"),
    # ⚠️ int→long variable type change: castxml parses type from header but
    #    global var definitions in .c may not appear in ELF dynsym reliably → NO_CHANGE
    ("case11_global_var_type", "BREAKING", "v1.c", "v2.c"),
    # ✅ Function inlined away → disappears from .so → FUNC_REMOVED → BREAKING
    ("case12_function_removed", "BREAKING", "v1.c", "v2.c"),
    # ✅ Unversioned→versioned: ld.so soft-matches → COMPATIBLE (adding versioning is safe)
    ("case13_symbol_versioning", "COMPATIBLE", "bad.c", "good.c"),
    # ✅ Class size change (private member added) → TYPE_SIZE_CHANGED → BREAKING
    ("case14_cpp_class_size", "BREAKING", "v1.cpp", "v2.cpp"),
    # ✅ noexcept removed → FUNC_NOEXCEPT_REMOVED → BREAKING (castxml sees noexcept attr)
    ("case15_noexcept_change", "BREAKING", "v1.cpp", "v2.cpp"),
    # ✅ Symbol appears in v2 that was inline in v1 → FUNC_ADDED → COMPATIBLE
    ("case16_inline_to_non_inline", "COMPATIBLE", "v1.hpp", "v2.hpp"),
    # ✅ Explicit-instantiated template size grows → TYPE_SIZE_CHANGED → BREAKING
    ("case17_template_abi", "BREAKING", "v1.hpp", "v2.hpp"),
    # ✅ castxml processes headers transitively: ThirdPartyHandle (4→8 bytes) detected
    #    via TYPE_SIZE_CHANGED → BREAKING. This is correct behaviour — the struct grew.
    ("case18_dependency_leak", "BREAKING", "foo_v1.h", "foo_v2.h"),
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

    # Copy case dir to tmp_path for isolated build (no artifacts in source tree,
    # no race conditions when tests run in parallel)
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
        # Skip if castxml itself failed (environment issue), fail if abicheck logic crashed
        if "castxml" in r1.stderr.lower() or "not found" in r1.stderr.lower():
            pytest.skip(f"castxml unavailable for {case_name}:\n{r1.stderr[:300]}")
        pytest.fail(f"abicheck dump v1 failed in {case_name}:\n{r1.stderr[:500]}")

    # Dump v2
    r2 = subprocess.run(
        ["abicheck", "dump", str(libv2), "-H", str(header2), "-o", str(snap2)],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if r2.returncode != 0:
        if "castxml" in r2.stderr.lower() or "not found" in r2.stderr.lower():
            pytest.skip(f"castxml unavailable for {case_name}:\n{r2.stderr[:300]}")
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
