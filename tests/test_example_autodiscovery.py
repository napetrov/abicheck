"""Integration tests — auto-discovery of all example cases.

Replaces the hard-coded CASES list in test_abi_examples.py with directory
scanning so every new example added to examples/ is automatically tested
without touching this file.

Layout support:
  • v1/v2     — examples/caseXX/v1.c(pp)  + v2.c(pp)  [+ v1.h/.hpp]
  • old/new   — examples/caseXX/old/lib.c + new/lib.c  [+ lib.h/.hpp]
  • good/bad  — examples/caseXX/bad.c (v1) + good.c (v2)  [bad=before, good=fixed]
  • libfoo    — examples/caseXX/libfoo_v1.c + libfoo_v2.c

Expected verdicts are loaded from examples/ground_truth.json (single source
of truth). Set a case to null in ground_truth.json to skip it entirely.

Cross-platform: cases declare supported platforms in ground_truth.json.
Build uses CMake when a CMakeLists.txt is present, falling back to direct
compilation otherwise.

Marked `@pytest.mark.integration` — requires a C/C++ compiler + castxml in PATH.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_DIR     = Path(__file__).parent.parent
EXAMPLES_DIR = REPO_DIR / "examples"

# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------
def _current_platform() -> str:
    """Return the platform tag used in ground_truth.json."""
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return sys.platform

CURRENT_PLATFORM = _current_platform()

def _shared_lib_suffix() -> str:
    """Return the shared library file extension for the current platform."""
    if sys.platform == "darwin":
        return ".dylib"
    if sys.platform == "win32":
        return ".dll"
    return ".so"

SHARED_LIB_SUFFIX = _shared_lib_suffix()

# ---------------------------------------------------------------------------
# Expected verdicts and known gaps — loaded from ground_truth.json.
# Single source of truth: add cases / known_gap fields there, not here.
# To skip a case, set its "expected" value to null in ground_truth.json.
# ---------------------------------------------------------------------------
_GT_PATH = REPO_DIR / "examples" / "ground_truth.json"
_gt_data = json.loads(_GT_PATH.read_text())
EXPECTED: dict[str, str | None] = {
    k: v.get("expected") for k, v in _gt_data["verdicts"].items()
}
# platforms: case_name → list of supported platforms
PLATFORMS: dict[str, list[str]] = {
    k: v.get("platforms", ["linux", "macos", "windows"])
    for k, v in _gt_data["verdicts"].items()
}
# known_gap: case_name → xfail reason (sourced from ground_truth.json)
KNOWN_GAPS: dict[str, str] = {
    k: v["known_gap"]
    for k, v in _gt_data["verdicts"].items()
    if "known_gap" in v
}


# ---------------------------------------------------------------------------
# Layout detection helpers
# ---------------------------------------------------------------------------
def _find_sources(
    case_dir: Path,
) -> tuple[Path, Path, Path | None, Path | None]:
    """Return (v1_src, v2_src, v1_hdr, v2_hdr).

    Raises pytest.skip() if no recognised layout is found or if a required
    v2 source is missing (only case04_no_change legitimately has no v2).
    """
    def _hdr(base_dir: Path, stem: str) -> Path | None:
        for ext in (".h", ".hpp"):
            h = base_dir / f"{stem}{ext}"
            if h.exists():
                return h
        return None

    # v1/v2 layout
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"v1{ext}"
        if v1.exists():
            v2 = case_dir / f"v2{ext}"
            if not v2.exists():
                if case_dir.name == "case04_no_change":
                    v2 = v1  # intentional: identical sources → NO_CHANGE
                else:
                    pytest.fail(f"{case_dir.name}: v2 source missing — broken fixture")
            return v1, v2, _hdr(case_dir, "v1"), _hdr(case_dir, "v2")

    # old/new layout (cases 19+)
    old_dir, new_dir = case_dir / "old", case_dir / "new"
    if old_dir.is_dir() and new_dir.is_dir():
        for ext in (".c", ".cpp"):
            v1 = old_dir / f"lib{ext}"
            if v1.exists():
                v2 = new_dir / f"lib{ext}"
                if not v2.exists():
                    pytest.fail(f"{case_dir.name}: new/lib{ext} missing — broken fixture")
                v1h = _hdr(old_dir, "lib")
                v2h = _hdr(new_dir, "lib")
                return v1, v2, v1h, v2h

    # good/bad layout (cases 05, 06, 13)
    # Convention: bad=v1 (before, problematic state), good=v2 (after, fixed state).
    # Comparing bad→good reveals symbol removals = BREAKING for callers.
    for ext in (".c", ".cpp"):
        bad = case_dir / f"bad{ext}"
        if bad.exists():
            good = case_dir / f"good{ext}"
            if not good.exists():
                pytest.fail(f"{case_dir.name}: good{ext} missing — broken fixture")
            return bad, good, None, None

    # libfoo_v1/v2 layout (case18)
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"libfoo_v1{ext}"
        if v1.exists():
            v2 = case_dir / f"libfoo_v2{ext}"
            if not v2.exists():
                pytest.fail(f"{case_dir.name}: libfoo_v2{ext} missing — broken fixture")
            return v1, v2, _hdr(case_dir, "foo_v1"), _hdr(case_dir, "foo_v2")

    pytest.skip(f"{case_dir.name}: no recognised source layout")


def _find_compiler() -> str | None:
    """Find a C compiler available on this platform."""
    if sys.platform == "win32":
        # Prefer cl.exe on Windows, fall back to gcc (MinGW)
        for cc in ("cl", "gcc", "clang"):
            if shutil.which(cc):
                return cc
    elif sys.platform == "darwin":
        for cc in ("clang", "gcc"):
            if shutil.which(cc):
                return cc
    else:
        for cc in ("gcc", "clang"):
            if shutil.which(cc):
                return cc
    return None


def _find_cxx_compiler() -> str | None:
    """Find a C++ compiler available on this platform."""
    if sys.platform == "win32":
        for cxx in ("cl", "g++", "clang++"):
            if shutil.which(cxx):
                return cxx
    elif sys.platform == "darwin":
        for cxx in ("clang++", "g++"):
            if shutil.which(cxx):
                return cxx
    else:
        for cxx in ("g++", "clang++"):
            if shutil.which(cxx):
                return cxx
    return None


def _compile_shared(src: Path, out: Path) -> None:
    """Compile *src* into a shared library at *out*.

    Cross-platform: uses the appropriate compiler and flags for the current OS.
    Raises ``pytest.fail`` (not skip) on compiler errors so that broken
    fixtures are surfaced immediately rather than silently green-skipped.
    Skip is only appropriate when the *tool* (compiler) is absent.
    """
    is_cpp = src.suffix in (".cpp",)

    if is_cpp:
        compiler = _find_cxx_compiler()
    else:
        compiler = _find_compiler()

    if not compiler:
        lang = "C++" if is_cpp else "C"
        pytest.skip(f"No {lang} compiler found in PATH")

    if compiler == "cl":
        # MSVC
        args = [compiler, "/LD", "/Zi", "/Fe:" + str(out), str(src)]
    elif sys.platform == "darwin":
        args = [compiler, "-dynamiclib", "-g", "-Og", "-fvisibility=default",
                "-install_name", "@rpath/lib.dylib",
                "-o", str(out), str(src)]
    else:
        args = [compiler, "-shared", "-fPIC", "-g", "-Og", "-fvisibility=default",
                "-o", str(out), str(src)]

    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.fail(
            f"Compile failed for {src.name} (exit {r.returncode}):\n{r.stderr[:800]}"
        )


def _build_with_cmake(case_dir: Path, build_dir: Path) -> tuple[Path, Path]:
    """Build a case using CMake. Returns (v1_lib, v2_lib) paths."""
    cmake = shutil.which("cmake")
    if not cmake:
        pytest.skip("cmake not found in PATH")

    case_name = case_dir.name
    case_out = build_dir / case_name

    # Configure
    r = subprocess.run(
        [cmake, "-S", str(case_dir.parent), "-B", str(build_dir),
         "-DCMAKE_BUILD_TYPE=Debug"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        pytest.fail(f"cmake configure failed for {case_name}:\n{r.stderr[:600]}")

    # Build only this case's targets (--config for multi-config generators)
    v1_target = f"{case_name}_v1"
    v2_target = f"{case_name}_v2"
    r = subprocess.run(
        [cmake, "--build", str(build_dir), "--target", v1_target, v2_target,
         "--config", "Debug"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        pytest.fail(f"cmake build failed for {case_name}:\n{r.stderr[:600]}")

    # Find the built libraries
    v1_lib = _find_built_lib(case_out, "v1")
    v2_lib = _find_built_lib(case_out, "v2")

    if not v1_lib or not v2_lib:
        pytest.fail(
            f"{case_name}: CMake build did not produce libv1/libv2 in {case_out}\n"
            f"Contents: {list(case_out.iterdir()) if case_out.exists() else 'dir missing'}"
        )

    return v1_lib, v2_lib


def _find_built_lib(directory: Path, name: str) -> Path | None:
    """Find a shared library named *name* in *directory* (any platform extension).

    Also checks common multi-config generator subdirectories (Debug/, Release/)
    in case the per-config output directory overrides were not applied.
    """
    if not directory.exists():
        return None
    # Directories to search: the directory itself, then config subdirs
    search_dirs = [directory]
    for cfg in ("Debug", "Release", "RelWithDebInfo", "MinSizeRel"):
        sub = directory / cfg
        if sub.is_dir():
            search_dirs.append(sub)
    for search_dir in search_dirs:
        for prefix in ("lib", ""):
            for suffix in (".so", ".dylib", ".dll"):
                lib = search_dir / f"{prefix}{name}{suffix}"
                if lib.exists():
                    return lib
    return None


# ---------------------------------------------------------------------------
# Auto-discovery: build test parameter list
# ---------------------------------------------------------------------------
def _collect_cases() -> list[tuple[str, str | None]]:
    cases = []
    for d in sorted(EXAMPLES_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("case"):
            continue
        expected = EXPECTED.get(d.name, "UNKNOWN")
        cases.append((d.name, expected))
    return cases


_ALL_CASES = _collect_cases()

# ---------------------------------------------------------------------------
# Parametrized integration test
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.parametrize(
    "case_name,expected_verdict",
    [(c, e) for c, e in _ALL_CASES if e is not None],
    ids=[c for c, e in _ALL_CASES if e is not None],
)
def test_example_pipeline(case_name: str, expected_verdict: str, tmp_path: Path) -> None:
    """Compile → dump → compare for every example case."""
    # --- Platform filter ---
    case_platforms = PLATFORMS.get(case_name, ["linux", "macos", "windows"])
    if CURRENT_PLATFORM not in case_platforms:
        pytest.skip(
            f"{case_name} not supported on {CURRENT_PLATFORM} "
            f"(requires {case_platforms})"
        )

    if not shutil.which("castxml"):
        pytest.skip("castxml not found in PATH")

    case_dir = EXAMPLES_DIR / case_name
    assert case_dir.is_dir(), f"Case directory not found: {case_dir}"

    v1_src, v2_src, v1_hdr, v2_hdr = _find_sources(case_dir)

    # Build strategy:
    # 1. CMake (if CMakeLists.txt exists) — cross-platform, handles special flags
    # 2. Direct compilation fallback — simple cases without special flags
    has_cmake_file = (case_dir / "CMakeLists.txt").exists()
    has_cmake = bool(shutil.which("cmake"))

    if has_cmake_file and has_cmake:
        build_dir = tmp_path / "cmake_build"
        v1_lib, v2_lib = _build_with_cmake(case_dir, build_dir)
        # Resolve header paths — headers stay in the source tree
        headers_v1 = [v1_hdr] if v1_hdr and v1_hdr.exists() else []
        headers_v2 = [v2_hdr] if v2_hdr and v2_hdr.exists() else []
    elif has_cmake_file and not has_cmake:
        # CMakeLists.txt exists but cmake is not available — check if the case
        # needs special build flags that direct compilation cannot replicate.
        cmake_text = (case_dir / "CMakeLists.txt").read_text()
        _special = ("FORCE_INCLUDE", "LINK_OPTIONS", "COMPILE_OPTIONS",
                    "fvisibility", "version-script", "soname")
        if any(tok in cmake_text for tok in _special):
            pytest.skip(
                f"{case_name} requires cmake (CMakeLists.txt has special "
                f"build flags) but cmake is not in PATH"
            )
        # Simple case — safe to compile directly
        v1_lib = tmp_path / f"libv1{SHARED_LIB_SUFFIX}"
        v2_lib = tmp_path / f"libv2{SHARED_LIB_SUFFIX}"
        _compile_shared(v1_src, v1_lib)
        _compile_shared(v2_src, v2_lib)
        headers_v1 = [v1_hdr] if v1_hdr and v1_hdr.exists() else []
        headers_v2 = [v2_hdr] if v2_hdr and v2_hdr.exists() else []
    else:
        # Fallback: direct compilation (works for simple cases)
        v1_lib = tmp_path / f"libv1{SHARED_LIB_SUFFIX}"
        v2_lib = tmp_path / f"libv2{SHARED_LIB_SUFFIX}"
        _compile_shared(v1_src, v1_lib)
        _compile_shared(v2_src, v2_lib)
        headers_v1 = [v1_hdr] if v1_hdr and v1_hdr.exists() else []
        headers_v2 = [v2_hdr] if v2_hdr and v2_hdr.exists() else []

    # Run abicheck pipeline via Python API (always uses THIS repo's code)
    from abicheck.checker import compare
    from abicheck.dumper import dump

    try:
        snap1 = dump(v1_lib, headers=headers_v1, version="v1")
        snap2 = dump(v2_lib, headers=headers_v2, version="v2")
    except Exception as exc:
        pytest.fail(f"{case_name}: dump failed: {exc}")

    result = compare(snap1, snap2)
    got = result.verdict.value.upper()

    def _normalize(v: str) -> str:
        return "COMPATIBLE" if v in ("API_BREAK", "COMPATIBLE") else v

    # Known gaps: xfail when verdict disagrees, pass through when fixed
    if case_name in KNOWN_GAPS:
        if _normalize(got) != _normalize(expected_verdict):
            pytest.xfail(KNOWN_GAPS[case_name])

    assert _normalize(got) == _normalize(expected_verdict), (
        f"{case_name}: expected={expected_verdict!r}, got={got!r}\n"
        f"Changes:\n" +
        "\n".join(f"  {c.kind.value}: {c.description}" for c in result.changes)
    )
