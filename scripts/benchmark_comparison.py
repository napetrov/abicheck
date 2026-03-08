#!/usr/bin/env python3
"""
Benchmark: abicheck vs ABICC vs abidiff on abicheck examples.

Runs all three tools on each example pair (v1/v2) and prints a comparison table.
abidiff is run twice: without headers (ELF-only) and with --headers-dir.

Usage: python3 scripts/benchmark_comparison.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from dataclasses import dataclass, field
from pathlib import Path

REPO_DIR     = Path(__file__).parent.parent
EXAMPLES_DIR = REPO_DIR / "examples"
REPORT_DIR   = REPO_DIR / "benchmark_reports"
BUILD_DIR    = REPORT_DIR / "_build"


@dataclass
class ToolResult:
    verdict: str
    changes: list[str] = field(default_factory=list)
    raw_output: str = ""
    report_path: str = ""


# ── Compile ───────────────────────────────────────────────────────────────────
def compile_so(src: Path, out_so: Path) -> bool:
    compiler = "g++" if src.suffix == ".cpp" else "gcc"
    r = subprocess.run(
        [compiler, "-shared", "-fPIC", "-g", "-fvisibility=default", "-o", str(out_so), str(src)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"    [compile error] {src}: {r.stderr[:120]}")
    return r.returncode == 0


def make_header(src: Path, out_h: Path) -> None:
    """Copy explicit .h/.hpp if present.

    For C sources without a .h, generates a minimal header by stripping function
    bodies. Not suitable for C++ sources — callers must provide explicit .h/.hpp.
    Warns when falling back to C-scraper to catch cases where a .h should be added.
    """
    for ext in (".h", ".hpp"):
        h = src.with_suffix(ext)
        if h.exists():
            shutil.copy(h, out_h)
            return
    if src.suffix == ".c":
        print(f"    [warn] no explicit .h for {src.name} — generating from source (add a .h file)")
        lines = []
        for line in src.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("/*", "*", "//")):
                lines.append(line)
                continue
            if "{" in stripped and not stripped.startswith("#"):
                decl = stripped.split("{")[0].strip().rstrip()
                if decl and not decl.endswith(";"):
                    lines.append(decl + ";")
            elif "}" not in stripped:
                lines.append(line)
        out_h.write_text("\n".join(lines))
    # For .cpp without explicit .h: leave out_h absent — ELF-only mode


def _best_h(ver: str, bdir_h: Path, src_dir: Path) -> Path:
    """Return the best available header: explicit in src_dir, then generated copy."""
    for ext in (".h", ".hpp"):
        p = src_dir / f"{ver}{ext}"
        if p.exists():
            return p
    return bdir_h  # may not exist — callers must check .exists()


# ── abicheck ──────────────────────────────────────────────────────────────────
def run_abicheck(v1_so: Path, v2_so: Path, v1_h: Path, v2_h: Path,
                 case: str, rdir: Path) -> ToolResult:
    try:
        from abicheck.checker import compare
        from abicheck.dumper import dump
        from abicheck.reporter import to_json, to_markdown
        from abicheck.sarif import to_sarif_str

        hdrs_v1 = [v1_h] if v1_h.exists() else []
        hdrs_v2 = [v2_h] if v2_h.exists() else []

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            old = dump(v1_so, headers=hdrs_v1, version="v1")
            new = dump(v2_so, headers=hdrs_v2, version="v2")

        result = compare(old, new)

        (rdir / f"{case}_abicheck.md").write_text(to_markdown(result))
        (rdir / f"{case}_abicheck.json").write_text(to_json(result))
        (rdir / f"{case}_abicheck.sarif").write_text(to_sarif_str(result))

        changes = [f"{c.kind.value}: {c.symbol}" for c in result.changes]
        return ToolResult(verdict=result.verdict.value, changes=changes,
                          raw_output=to_markdown(result),
                          report_path=f"{case}_abicheck.md")
    except Exception as exc:  # noqa: BLE001
        return ToolResult(verdict="ERROR", raw_output=str(exc))


# ── abidiff (two modes) ───────────────────────────────────────────────────────
def _abidiff_verdict(returncode: int) -> str:
    if returncode & 1:
        return "ERROR"
    if returncode & 8:
        return "BREAKING"
    if returncode & 4:
        return "COMPATIBLE"
    return "NO_CHANGE"


def run_abidiff(v1_so: Path, v2_so: Path, case: str, rdir: Path,
                headers_dir: Path | None = None) -> ToolResult:
    """Run abidiff, optionally with --headers-dir for public-API filtering."""
    if not shutil.which("abidiff"):
        return ToolResult(verdict="SKIP")

    cmd = ["abidiff", "--no-show-locs"]
    if headers_dir and headers_dir.is_dir():
        cmd += ["--headers-dir1", str(headers_dir), "--headers-dir2", str(headers_dir)]
    cmd += [str(v1_so), str(v2_so)]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    verdict = _abidiff_verdict(r.returncode)
    out = r.stdout or r.stderr
    suffix = "_hdr" if headers_dir else ""
    (rdir / f"{case}_abidiff{suffix}.txt").write_text(out)
    changes = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("[")]
    return ToolResult(verdict=verdict, changes=changes, raw_output=out,
                      report_path=f"{case}_abidiff{suffix}.txt")


# ── ABICC ─────────────────────────────────────────────────────────────────────
def run_abicc(v1_so: Path, v2_so: Path, v1_h: Path, v2_h: Path,
              case: str, rdir: Path) -> ToolResult:
    if not shutil.which("abi-compliance-checker"):
        return ToolResult(verdict="SKIP")

    def xml(so: Path, h: Path, ver: str, out: Path) -> None:
        hdir = str(h.parent) if h.exists() else "/usr/include"
        out.write_text(
            f"<descriptor>\n"
            f"  <version>{ver}</version>\n"
            f"  <headers>{hdir}/</headers>\n"
            f"  <libs>{so}</libs>\n"
            f"</descriptor>\n"
        )

    v1_xml = rdir / f"{case}_v1.xml"
    v2_xml = rdir / f"{case}_v2.xml"
    xml(v1_so, v1_h, "v1", v1_xml)
    xml(v2_so, v2_h, "v2", v2_xml)

    html_out = rdir / f"{case}_abicc_report.html"
    r = subprocess.run(
        ["abi-compliance-checker", "-l", case,
         "-old", str(v1_xml), "-new", str(v2_xml),
         "-report-path", str(html_out)],
        capture_output=True, text=True, timeout=120,
    )

    out = r.stdout + r.stderr
    (rdir / f"{case}_abicc.txt").write_text(out)

    if r.returncode == 1:
        verdict = "BREAKING"
    elif "Binary compatibility: 100%" in out:
        verdict = "NO_CHANGE"
    elif r.returncode == 0:
        verdict = "COMPATIBLE"
    else:
        verdict = "ERROR"

    changes = [ln.strip() for ln in out.splitlines()
               if any(k in ln for k in ("removed", "added", "changed")) and ln.strip()]
    return ToolResult(verdict=verdict, changes=changes[:8], raw_output=out,
                      report_path=f"{case}_abicc_report.html")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _col(v: str) -> str:
    colors = {"BREAKING": "\033[91m", "COMPATIBLE": "\033[93m",
              "NO_CHANGE": "\033[92m", "ERROR": "\033[95m", "SKIP": "\033[90m"}
    return f"{colors.get(v, '')}{v:<14}\033[0m"


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(exist_ok=True)

    cases = sorted(
        d for d in EXAMPLES_DIR.iterdir()
        if d.is_dir() and ((d / "v1.c").exists() or (d / "v1.cpp").exists())
    )

    results: list[dict[str, object]] = []

    print(f"\n{'Case':<35} {'abicheck':<16} {'abidiff':<16} {'abidiff+hdr':<16} {'ABICC':<14}")
    print("─" * 100)

    for case_dir in cases:
        name    = case_dir.name
        ext     = ".cpp" if (case_dir / "v1.cpp").exists() else ".c"
        v1_src  = case_dir / f"v1{ext}"
        v2_src  = case_dir / f"v2{ext}"
        if not v2_src.exists():
            v2_src = v1_src   # case04: no change

        rdir = REPORT_DIR / name
        rdir.mkdir(exist_ok=True)
        bdir = BUILD_DIR / name
        bdir.mkdir(exist_ok=True)

        v1_so = bdir / "lib_v1.so"
        v2_so = bdir / "lib_v2.so"
        v1_h  = bdir / "v1.h"
        v2_h  = bdir / "v2.h"

        if not compile_so(v1_src, v1_so) or not compile_so(v2_src, v2_so):
            print(f"  {name:<33} COMPILE_ERR")
            continue

        make_header(v1_src, v1_h)
        make_header(v2_src, v2_h)

        eff_v1_h = _best_h("v1", v1_h, case_dir)
        eff_v2_h = _best_h("v2", v2_h, case_dir)

        ac      = run_abicheck(v1_so, v2_so, eff_v1_h, eff_v2_h, name, rdir)
        ab      = run_abidiff(v1_so, v2_so, name, rdir)
        ab_hdr  = run_abidiff(v1_so, v2_so, name, rdir, headers_dir=case_dir)
        acc     = run_abicc(v1_so, v2_so, eff_v1_h, eff_v2_h, name, rdir)

        print(f"  {name:<33} {_col(ac.verdict)} {_col(ab.verdict)} {_col(ab_hdr.verdict)} {_col(acc.verdict)}")

        results.append({
            "case":             name,
            "abicheck":         ac.verdict,
            "abidiff":          ab.verdict,
            "abidiff_headers":  ab_hdr.verdict,
            "abicc":            acc.verdict,
            "abicheck_changes": ac.changes,
            "abidiff_changes":  ab.changes,
            "abicc_changes":    acc.changes,
        })

    # ── Summary ──────────────────────────────────────────────────────────────
    valid = [r for r in results
             if "SKIP" not in (r["abicheck"], r["abidiff"], r["abicc"])]
    n     = len(valid)
    all3  = sum(1 for r in valid if r["abicheck"] == r["abidiff"] == r["abicc"])
    ac_ab = sum(1 for r in valid if r["abicheck"] == r["abidiff"])
    ac_acc = sum(1 for r in valid if r["abicheck"] == r["abicc"])

    print("\n" + "─" * 100)
    print(f"  Total cases: {len(results)}   (valid for comparison: {n})")
    print(f"  All three agree:          {all3}/{n} ({100 * all3 // n if n else 0}%)")
    print(f"  abicheck == abidiff:      {ac_ab}/{n}")
    print(f"  abicheck == ABICC:        {ac_acc}/{n}")

    divs = [r for r in valid if r["abicheck"] != r["abidiff"] or r["abicheck"] != r["abicc"]]
    if divs:
        print("\n  Divergences:")
        for r in divs:
            print(f"    {r['case']:<35} ac={r['abicheck']:<12} "
                  f"ab={r['abidiff']:<12} ab+hdr={r['abidiff_headers']:<12} "
                  f"abicc={r['abicc']}")

    summary = REPORT_DIR / "comparison_summary.json"
    summary.write_text(json.dumps(results, indent=2))
    print(f"\n  Reports: {REPORT_DIR}/")
    print(f"  Summary: {summary}")


if __name__ == "__main__":
    main()
