# pylint: disable=too-many-branches,too-many-statements,too-many-locals,too-many-arguments,too-many-return-statements
"""validate_examples.py — standalone CLI validation of all abicheck example cases.

Reads expected verdicts from examples/ground_truth.json, compiles each
example with the platform's native compiler, runs abicheck dump+compare,
and reports results.

Cross-platform: respects the ``platforms`` field in ground_truth.json and
uses CMake when a CMakeLists.txt is present.  Falls back to direct
compilation for simple cases.

Usage:
    python tests/validate_examples.py                   # all cases
    python tests/validate_examples.py case01 case07     # filter by name substring
    python tests/validate_examples.py --fail-fast       # stop on first failure
    python tests/validate_examples.py --json            # machine-readable output

Exit codes:
    0  all pass (known gaps are xfail, not failures)
    1  one or more unexpected failures
    2  environment error (tools missing, etc.)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

REPO_DIR = Path(__file__).parent.parent
EXAMPLES_DIR = REPO_DIR / "examples"
GROUND_TRUTH = EXAMPLES_DIR / "ground_truth.json"


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
    if sys.platform == "darwin":
        return ".dylib"
    if sys.platform == "win32":
        return ".dll"
    return ".so"


SHARED_LIB_SUFFIX = _shared_lib_suffix()


def _find_compiler(is_cpp: bool = False) -> str | None:
    """Find a C/C++ compiler available on this platform."""
    if is_cpp:
        candidates = {
            "win32": ["cl", "g++", "clang++"],
            "darwin": ["clang++", "g++"],
        }.get(sys.platform, ["g++", "clang++"])
    else:
        candidates = {
            "win32": ["cl", "gcc", "clang"],
            "darwin": ["clang", "gcc"],
        }.get(sys.platform, ["gcc", "clang"])
    for cc in candidates:
        if shutil.which(cc):
            return cc
    return None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
class CaseResult(NamedTuple):
    name: str
    status: str          # PASS | FAIL | XFAIL | SKIP | ERROR
    expected: str | None
    got: str | None
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_sources(
    case_dir: Path,
) -> tuple[Path, Path, Path | None, Path | None] | None:
    """Return (v1_src, v2_src, v1_hdr, v2_hdr) or None if no layout matched."""

    def _hdr(base: Path, stem: str) -> Path | None:
        for ext in (".h", ".hpp"):
            h = base / f"{stem}{ext}"
            if h.exists():
                return h
        return None

    # v1/v2 layout
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"v1{ext}"
        if v1.exists():
            v2 = case_dir / f"v2{ext}"
            if not v2.exists() and case_dir.name == "case04_no_change":
                v2 = v1
            if v2.exists():
                return v1, v2, _hdr(case_dir, "v1"), _hdr(case_dir, "v2")

    # old/new layout
    old_dir, new_dir = case_dir / "old", case_dir / "new"
    if old_dir.is_dir() and new_dir.is_dir():
        for ext in (".c", ".cpp"):
            v1 = old_dir / f"lib{ext}"
            if v1.exists():
                v2 = new_dir / f"lib{ext}"
                if v2.exists():
                    return v1, v2, _hdr(old_dir, "lib"), _hdr(new_dir, "lib")

    # good/bad layout
    for ext in (".c", ".cpp"):
        bad = case_dir / f"bad{ext}"
        if bad.exists():
            good = case_dir / f"good{ext}"
            if good.exists():
                return bad, good, None, None

    # libfoo_v1/v2 layout
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"libfoo_v1{ext}"
        if v1.exists():
            v2 = case_dir / f"libfoo_v2{ext}"
            if v2.exists():
                return v1, v2, _hdr(case_dir, "foo_v1"), _hdr(case_dir, "foo_v2")

    return None


def _compile(src: Path, out: Path) -> str | None:
    """Compile src → shared lib. Returns error string on failure, None on success."""
    is_cpp = src.suffix == ".cpp"
    compiler = _find_compiler(is_cpp)
    if not compiler:
        return f"no {'C++' if is_cpp else 'C'} compiler found"

    if compiler == "cl":
        args = [compiler, "/LD", "/Zi", "/Fe:" + str(out), str(src)]
    elif sys.platform == "darwin":
        args = [compiler, "-dynamiclib", "-g", "-Og", "-fvisibility=default",
                "-o", str(out), str(src)]
    else:
        args = [compiler, "-shared", "-fPIC", "-g", "-Og", "-fvisibility=default",
                "-o", str(out), str(src)]

    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return None if r.returncode == 0 else r.stderr[:600]


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


def _build_with_cmake(case_dir: Path, build_dir: Path) -> tuple[Path | None, Path | None, str]:
    """Build a case using CMake. Returns (v1_lib, v2_lib, error_msg)."""
    cmake = shutil.which("cmake")
    if not cmake:
        return None, None, "cmake not found"

    case_name = case_dir.name
    case_out = build_dir / case_name

    r = subprocess.run(
        [cmake, "-S", str(case_dir.parent), "-B", str(build_dir),
         "-DCMAKE_BUILD_TYPE=Debug"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        return None, None, f"cmake configure failed: {r.stderr[:300]}"

    v1_target = f"{case_name}_v1"
    v2_target = f"{case_name}_v2"
    r = subprocess.run(
        [cmake, "--build", str(build_dir), "--target", v1_target, v2_target,
         "--config", "Debug"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        return None, None, f"cmake build failed: {r.stderr[:300]}"

    v1_lib = _find_built_lib(case_out, "v1")
    v2_lib = _find_built_lib(case_out, "v2")

    if not v1_lib or not v2_lib:
        return None, None, f"CMake did not produce libv1/libv2 in {case_out}"

    return v1_lib, v2_lib, ""


def _normalize_verdict(v: str) -> str:
    """Normalize verdict for comparison."""
    return v


# ---------------------------------------------------------------------------
# Core: run one case
# ---------------------------------------------------------------------------
def run_case(
    name: str,
    entry: dict,
    tmp_base: Path,
    fail_fast: bool = False,
) -> CaseResult:
    expected_raw = entry.get("expected")
    skip = entry.get("skip", False)
    known_gap = entry.get("known_gap")

    if skip:
        return CaseResult(name, "SKIP", expected_raw, None, entry.get("reason", "skip=true"))

    # Platform filter
    platforms = entry.get("platforms", ["linux", "macos", "windows"])
    if CURRENT_PLATFORM not in platforms:
        return CaseResult(name, "SKIP", expected_raw, None,
                          f"not supported on {CURRENT_PLATFORM} (requires {platforms})")

    case_dir = EXAMPLES_DIR / name
    if not case_dir.is_dir():
        return CaseResult(name, "ERROR", expected_raw, None, "directory not found")

    sources = _find_sources(case_dir)
    if sources is None:
        return CaseResult(name, "ERROR", expected_raw, None,
                          "no recognised source layout (harness error — fix example or mark skip in ground_truth.json)")

    v1_src, v2_src, v1_hdr, v2_hdr = sources
    tmp = tmp_base / name
    tmp.mkdir(parents=True)

    # Build strategy: CMake > direct compilation
    has_cmake_file = (case_dir / "CMakeLists.txt").exists()
    has_cmake = bool(shutil.which("cmake"))

    if has_cmake_file and has_cmake:
        cmake_build = tmp / "cmake_build"
        v1_so, v2_so, err = _build_with_cmake(case_dir, cmake_build)
        if err:
            return CaseResult(name, "ERROR", expected_raw, None, err)
        v1_hdr_path = v1_hdr
        v2_hdr_path = v2_hdr
    elif has_cmake_file and not has_cmake:
        # CMakeLists.txt exists but cmake is not available — check if the case
        # needs special build flags that direct compilation cannot replicate.
        cmake_text = (case_dir / "CMakeLists.txt").read_text()
        _special = ("FORCE_INCLUDE", "LINK_OPTIONS", "COMPILE_OPTIONS",
                     "fvisibility", "version-script", "soname")
        if any(tok in cmake_text for tok in _special):
            return CaseResult(name, "SKIP", expected_raw, None,
                              "requires cmake (CMakeLists.txt has special build flags)")
        v1_so = tmp / f"libv1{SHARED_LIB_SUFFIX}"
        v2_so = tmp / f"libv2{SHARED_LIB_SUFFIX}"
        err = _compile(v1_src, v1_so)
        if err:
            return CaseResult(name, "ERROR", expected_raw, None, f"compile v1 failed: {err[:200]}")
        err = _compile(v2_src, v2_so)
        if err:
            return CaseResult(name, "ERROR", expected_raw, None, f"compile v2 failed: {err[:200]}")
        v1_hdr_path = v1_hdr
        v2_hdr_path = v2_hdr

    # dump v1
    snap1 = tmp / "snap1.json"
    cmd_dump1 = [sys.executable, "-m", "abicheck.cli", "dump", str(v1_so), "-o", str(snap1)]
    if v1_hdr_path and Path(v1_hdr_path).exists():
        cmd_dump1 += ["-H", str(v1_hdr_path)]
    r1 = subprocess.run(cmd_dump1, capture_output=True, text=True, timeout=60)
    if r1.returncode != 0:
        return CaseResult(name, "ERROR", expected_raw, None, f"dump v1 failed: {r1.stderr[:200]}")

    # dump v2
    snap2 = tmp / "snap2.json"
    cmd_dump2 = [sys.executable, "-m", "abicheck.cli", "dump", str(v2_so), "-o", str(snap2)]
    if v2_hdr_path and Path(v2_hdr_path).exists():
        cmd_dump2 += ["-H", str(v2_hdr_path)]
    r2 = subprocess.run(cmd_dump2, capture_output=True, text=True, timeout=60)
    if r2.returncode != 0:
        return CaseResult(name, "ERROR", expected_raw, None, f"dump v2 failed: {r2.stderr[:200]}")

    # compare
    rc = subprocess.run(
        [sys.executable, "-m", "abicheck.cli", "compare", str(snap1), str(snap2), "--format", "json"],
        capture_output=True, text=True, timeout=60,
    )
    try:
        data = json.loads(rc.stdout)
        got = data.get("verdict", "UNKNOWN")
    except json.JSONDecodeError:
        return CaseResult(name, "ERROR", expected_raw, None,
                          f"invalid JSON from compare: {rc.stdout[:200]}")

    expected = expected_raw or "UNKNOWN"
    if _normalize_verdict(got) == _normalize_verdict(expected):
        return CaseResult(name, "PASS", expected_raw, got, "")

    if known_gap:
        return CaseResult(name, "XFAIL", expected_raw, got, known_gap)

    return CaseResult(
        name, "FAIL", expected_raw, got,
        f"expected={expected!r} got={got!r}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("filters", nargs="*",
                    help="Name substrings to filter cases (default: all)")
    ap.add_argument("--fail-fast", action="store_true",
                    help="Stop after first FAIL")
    ap.add_argument("--json", action="store_true", dest="json_out",
                    help="Machine-readable JSON output")
    ap.add_argument("--category", metavar="CAT",
                    help="Filter by category: breaking, compatible, bad_practice, api_break")
    args = ap.parse_args(argv)

    # Check that at least one compiler is available
    cc = _find_compiler(False)
    cxx = _find_compiler(True)
    if not cc and not cxx:
        print("ERROR: no C or C++ compiler found in PATH", file=sys.stderr)
        return 2

    if not shutil.which("castxml"):
        print("ERROR: required tool 'castxml' not found in PATH", file=sys.stderr)
        return 2

    try:
        __import__("abicheck")
    except Exception as exc:
        print(f"ERROR: abicheck module import failed: {exc}", file=sys.stderr)
        return 2

    # Load ground truth
    if not GROUND_TRUTH.exists():
        print(f"ERROR: {GROUND_TRUTH} not found", file=sys.stderr)
        return 2

    with open(GROUND_TRUTH) as f:
        gt = json.load(f)

    verdicts: dict[str, dict] = gt["verdicts"]

    # Filter cases
    names = sorted(verdicts.keys())
    if args.filters:
        names = [n for n in names if any(f in n for f in args.filters)]
    if args.category:
        names = [n for n in names if verdicts[n].get("category") == args.category]

    results: list[CaseResult] = []
    with tempfile.TemporaryDirectory(prefix="validate_examples_") as tmp_root:
        tmp_base = Path(tmp_root)
        for name in names:
            res = run_case(name, verdicts[name], tmp_base)
            results.append(res)
            if not args.json_out:
                icon = {"PASS": "✅", "FAIL": "❌", "XFAIL": "⚠️ ",
                        "SKIP": "⏭️ ", "ERROR": "💥"}.get(res.status, "?")
                msg = f"  {res.message}" if res.message else ""
                print(f"{icon} {res.name:<42}  {res.status}{msg}")
            if args.fail_fast and res.status == "FAIL":
                break

    # Summary
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    if args.json_out:
        print(json.dumps({
            "summary": counts,
            "results": [r._asdict() for r in results],
        }, indent=2))
    else:
        total = len(results)
        print(f"\n{'─'*60}")
        print(f"Total: {total}  " +
              "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    failures = counts.get("FAIL", 0) + counts.get("ERROR", 0)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
