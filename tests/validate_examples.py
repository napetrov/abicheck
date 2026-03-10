"""validate_examples.py — standalone CLI validation of all abicheck example cases.

Reads expected verdicts from examples/ground_truth.json, compiles each
example with gcc/g++, runs abicheck dump+compare, and reports results.

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
    compiler = "g++" if src.suffix == ".cpp" else "gcc"
    r = subprocess.run(
        [compiler, "-shared", "-fPIC", "-g", "-Og", "-fvisibility=default",
         "-o", str(out), str(src)],
        capture_output=True, text=True, timeout=30,
    )
    return None if r.returncode == 0 else r.stderr[:600]


def _normalize_verdict(v: str) -> str:
    """Normalize verdict for comparison.

    API_BREAK and COMPATIBLE are intentionally kept distinct so that a
    regression from API_BREAK to COMPATIBLE is caught as a test failure.
    """
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

    # Use the Makefile if the case ships one — ensures special build flags
    # (version scripts, extra link options) are applied as the example intends.
    if (case_dir / "Makefile").exists():
        import shutil as _shutil
        build_dir = tmp / "build"
        _shutil.copytree(str(case_dir), str(build_dir))
        r = subprocess.run(["make", "-C", str(build_dir)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return CaseResult(name, "ERROR", expected_raw, None,
                              f"make failed: {r.stderr[:300]}")
        v1_so = build_dir / "libv1.so"
        v2_so = build_dir / "libv2.so"
        if not v1_so.exists() or not v2_so.exists():
            return CaseResult(name, "ERROR", expected_raw, None,
                              "Makefile did not produce libv1.so / libv2.so")
        # Remap header path: relative to original case_dir → same relative path under build_dir
        if v1_hdr:
            try:
                rel = v1_hdr.relative_to(case_dir)
                v1_hdr_path = build_dir / rel
            except ValueError:
                v1_hdr_path = build_dir / v1_hdr.name
        else:
            v1_hdr_path = None
        if v2_hdr:
            try:
                rel = v2_hdr.relative_to(case_dir)
                v2_hdr_path = build_dir / rel
            except ValueError:
                v2_hdr_path = build_dir / v2_hdr.name
        else:
            v2_hdr_path = None
    else:
        v1_so = tmp / "libv1.so"
        v2_so = tmp / "libv2.so"
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
                    help="Filter by category: breaking, compatible, bad_practice, source_break")
    args = ap.parse_args(argv)

    # Check required tools
    for tool in ("gcc", "g++", "castxml"):
        if not shutil.which(tool):
            print(f"ERROR: required tool '{tool}' not found in PATH", file=sys.stderr)
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
