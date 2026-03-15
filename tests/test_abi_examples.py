"""Integration tests for ABI check examples (legacy — cases 01-18).

Superseded by test_example_autodiscovery.py which auto-discovers all cases.
Kept for backward compatibility. Uses CMake when available, falls back to
direct compilation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

# (case_dir_name, expected_verdict, header_v1, header_v2)
#
# Expected verdicts reflect what abicheck currently detects with castxml+ELF analysis:
#   DETECTED  — abicheck catches the break reliably
#   LIMITATION — break exists but abicheck cannot detect it yet (documented gap)
#   POLICY   — not a binary break; SONAME/versioning are policy issues
#
CASES = [
    # Symbol removed from ELF dynsym → FUNC_REMOVED → BREAKING
    ("case01_symbol_removal", "BREAKING", "v1.c", "v2.c"),
    # Parameter type change visible via castxml → FUNC_PARAMS_CHANGED → BREAKING
    ("case02_param_type_change", "BREAKING", "v1.c", "v2.c"),
    # New symbol added → FUNC_ADDED → COMPATIBLE
    ("case03_compat_addition", "COMPATIBLE", "v1.c", "v2.c"),
    # Identical libs → NO_CHANGE
    ("case04_no_change", "NO_CHANGE", "v1.c", "v1.c"),
    # SONAME is a policy attribute, not tracked as a binary ABI break.
    ("case05_soname", "COMPATIBLE", "bad.c", "good.c"),
    # internal_helper/another_impl hidden in good.c → removed from dynsym → BREAKING
    ("case06_visibility", "BREAKING", "bad.c", "good.c"),
    # Struct size change detected via castxml → TYPE_SIZE_CHANGED → BREAKING
    ("case07_struct_layout", "BREAKING", "v1.c", "v2.c"),
    # Enum member value changes detected via _diff_enums() → BREAKING
    ("case08_enum_value_change", "BREAKING", "v1.c", "v2.c"),
    # vtable reorder/change detected → TYPE_VTABLE_CHANGED → BREAKING
    ("case09_cpp_vtable", "BREAKING", "v1.cpp", "v2.cpp"),
    # Return type change detected via castxml → FUNC_RETURN_CHANGED → BREAKING
    ("case10_return_type", "BREAKING", "v1.c", "v2.c"),
    # Global var type change → BREAKING
    ("case11_global_var_type", "BREAKING", "v1.c", "v2.c"),
    # Function inlined away → disappears from .so → FUNC_REMOVED → BREAKING
    ("case12_function_removed", "BREAKING", "v1.c", "v2.c"),
    # Symbol versioning: checker strips @-suffix → symbols match → COMPATIBLE
    ("case13_symbol_versioning", "COMPATIBLE", "bad.c", "good.c"),
    # Class size change (private member added) → TYPE_SIZE_CHANGED → BREAKING
    ("case14_cpp_class_size", "BREAKING", "v1.cpp", "v2.cpp"),
    # noexcept removed → FUNC_NOEXCEPT_REMOVED → BREAKING
    ("case15_noexcept_change", "BREAKING", "v1.cpp", "v2.cpp"),
    # Symbol appears in v2 that was inline in v1 → FUNC_ADDED → COMPATIBLE
    ("case16_inline_to_non_inline", "COMPATIBLE", "v1.hpp", "v2.hpp"),
    # Explicit-instantiated template size grows → TYPE_SIZE_CHANGED → BREAKING
    ("case17_template_abi", "BREAKING", "v1.hpp", "v2.hpp"),
    # castxml processes headers transitively: ThirdPartyHandle (4→8 bytes) → BREAKING
    ("case18_dependency_leak", "BREAKING", "foo_v1.h", "foo_v2.h"),
]


def _shared_lib_suffix() -> str:
    if sys.platform == "darwin":
        return ".dylib"
    if sys.platform == "win32":
        return ".dll"
    return ".so"


def _find_compiler(is_cpp: bool = False) -> str | None:
    if is_cpp:
        candidates = {"win32": ["cl", "g++", "clang++"],
                       "darwin": ["clang++", "g++"]}.get(sys.platform, ["g++", "clang++"])
    else:
        candidates = {"win32": ["cl", "gcc", "clang"],
                       "darwin": ["clang", "gcc"]}.get(sys.platform, ["gcc", "clang"])
    for cc in candidates:
        if shutil.which(cc):
            return cc
    return None


def _compile_shared(src: Path, out: Path) -> bool:
    """Compile src into a shared library. Returns True on success."""
    is_cpp = src.suffix == ".cpp"
    compiler = _find_compiler(is_cpp)
    if not compiler:
        return False

    if compiler == "cl":
        args = [compiler, "/LD", "/Zi", "/Fe:" + str(out), str(src)]
    elif sys.platform == "darwin":
        args = [compiler, "-dynamiclib", "-g", "-Og", "-fvisibility=default",
                "-o", str(out), str(src)]
    else:
        args = [compiler, "-shared", "-fPIC", "-g", "-Og", "-fvisibility=default",
                "-o", str(out), str(src)]

    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode == 0


def _find_lib(directory: Path, name: str) -> Path | None:
    """Find a shared library in directory across platforms.

    Also checks multi-config generator subdirectories (Debug/, Release/).
    """
    if not directory.exists():
        return None
    search_dirs = [directory]
    for cfg in ("Debug", "Release", "RelWithDebInfo", "MinSizeRel"):
        sub = directory / cfg
        if sub.is_dir():
            search_dirs.append(sub)
    for search_dir in search_dirs:
        for prefix in ("lib", ""):
            for suffix in (".so", ".dylib", ".dll"):
                p = search_dir / f"{prefix}{name}{suffix}"
                if p.exists():
                    return p
    return None


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        pytest.skip(f"{name} not found in PATH")


# Load platform info from ground_truth.json
_gt_path = EXAMPLES_DIR / "ground_truth.json"
_gt_data = json.loads(_gt_path.read_text()) if _gt_path.exists() else {"verdicts": {}}
_PLATFORMS: dict[str, list[str]] = {
    k: v.get("platforms", ["linux", "macos", "windows"])
    for k, v in _gt_data["verdicts"].items()
}

def _current_platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return sys.platform


@pytest.mark.integration
@pytest.mark.parametrize("case_name,expected_verdict,hdr_v1,hdr_v2", CASES,
                         ids=[c[0] for c in CASES])
def test_abi_example(case_name, expected_verdict, hdr_v1, hdr_v2, tmp_path):
    _require_tool("castxml")

    # Platform filter
    platforms = _PLATFORMS.get(case_name, ["linux", "macos", "windows"])
    current = _current_platform()
    if current not in platforms:
        pytest.skip(f"{case_name} not supported on {current}")

    case_dir = EXAMPLES_DIR / case_name
    assert case_dir.is_dir(), f"Case directory not found: {case_dir}"

    build_dir = tmp_path / case_name
    shutil.copytree(str(case_dir), str(build_dir))

    suffix = _shared_lib_suffix()

    # Build strategy: CMake > direct compilation
    cmake_file = case_dir / "CMakeLists.txt"
    libv1 = None
    libv2 = None

    if cmake_file.exists() and shutil.which("cmake"):
        cmake_build = tmp_path / "cmake_build"
        r = subprocess.run(
            ["cmake", "-S", str(case_dir.parent), "-B", str(cmake_build),
             "-DCMAKE_BUILD_TYPE=Debug"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            r = subprocess.run(
                ["cmake", "--build", str(cmake_build),
                 "--target", f"{case_name}_v1", f"{case_name}_v2",
                 "--config", "Debug"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                out_dir = cmake_build / case_name
                libv1 = _find_lib(out_dir, "v1")
                libv2 = _find_lib(out_dir, "v2")

    if not libv1 or not libv2:
        # Fallback: direct compilation.
        # hdr_v1/hdr_v2 may be header names (e.g. v1.hpp, foo_v1.h) rather
        # than compilable source files. Try to find the actual source file.
        def _find_source(d: Path, hint: str) -> Path:
            """Resolve a compilable source from a hint that may be a header."""
            p = d / hint
            if p.suffix in (".c", ".cpp"):
                return p
            # hint is a header — look for matching source
            stem = p.stem
            for ext in (".c", ".cpp"):
                src = d / f"{stem}{ext}"
                if src.exists():
                    return src
            # libfoo pattern: foo_v1.h → libfoo_v1.c
            if stem.endswith(("_v1", "_v2")):
                base = stem[:-3]  # e.g. "foo"
                tag = stem[-3:]   # e.g. "_v1"
                for ext in (".c", ".cpp"):
                    src = d / f"lib{base}{tag}{ext}"
                    if src.exists():
                        return src
            return p  # best effort

        src_v1 = _find_source(build_dir, hdr_v1)
        src_v2 = _find_source(build_dir, hdr_v2)
        libv1 = tmp_path / f"libv1{suffix}"
        libv2 = tmp_path / f"libv2{suffix}"
        if not _compile_shared(src_v1, libv1):
            pytest.skip(f"compilation failed for {case_name} v1")
        if not _compile_shared(src_v2, libv2):
            pytest.skip(f"compilation failed for {case_name} v2")

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
