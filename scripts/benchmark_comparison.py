#!/usr/bin/env python3
"""
Benchmark: abicheck vs ABICC vs abidiff on abicheck examples.

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
    """Copy explicit .h/.hpp if present. For .cpp sources without .h, skip — do not
    generate broken fallback headers from naive regex scraping of C++ source."""
    # Prefer explicit .h next to source
    for ext in (".h", ".hpp"):
        h = src.with_suffix(ext)
        if h.exists():
            shutil.copy(h, out_h)
            return
    # For C sources without .h, generate minimal header by stripping bodies
    if src.suffix == ".c":
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
    # For .cpp without explicit .h: leave out_h absent — abicheck/ABICC will use ELF-only


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
    except Exception as exc:
        return ToolResult(verdict="ERROR", raw_output=str(exc))


# ── abidiff ───────────────────────────────────────────────────────────────────
def _abidiff_verdict(code: int) -> str:
    return (
        "ERROR" if code & 1 else
        "BREAKING" if code & 8 else
        "COMPATIBLE" if code & 4 else "NO_CHANGE"
    )


def run_abidiff(
    v1_so: Path,
    v2_so: Path,
    case: str,
    rdir: Path,
    headers_dir: Path | None = None,
    suffix: str = "",
) -> ToolResult:
    if not shutil.which("abidiff"):
        return ToolResult(verdict="SKIP")

    cmd = ["abidiff", "--no-show-locs"]
    if headers_dir is not None:
        cmd += ["--headers-dir1", str(headers_dir), "--headers-dir2", str(headers_dir)]
    cmd += [str(v1_so), str(v2_so)]

    report_name = f"{case}_abidiff{suffix}.txt"
    report_path = rdir / report_name

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        timeout_msg = (
            f"abidiff timed out after 30s for case '{case}'"
            f"{suffix or ''}: {exc}"
        )
        report_path.write_text(timeout_msg)
        return ToolResult(
            verdict="TIMEOUT",
            changes=[],
            raw_output=timeout_msg,
            report_path=report_name,
        )

    verdict = _abidiff_verdict(r.returncode)
    out = r.stdout or r.stderr
    report_path.write_text(out)
    changes = [line.strip() for line in out.splitlines() if line.strip().startswith("[")]
    return ToolResult(verdict=verdict, changes=changes, raw_output=out,
                      report_path=report_name)


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

    # exit 0 = compatible, 1 = incompatible
    if r.returncode == 1:
        verdict = "BREAKING"
    elif "Binary compatibility: 100%" in out:
        verdict = "NO_CHANGE"
    elif r.returncode == 0:
        verdict = "COMPATIBLE"
    else:
        verdict = "ERROR"

    changes = [line.strip() for line in out.splitlines()
               if any(k in line for k in ("removed", "added", "changed")) and line.strip()]
    return ToolResult(verdict=verdict, changes=changes[:8], raw_output=out,
                      report_path=f"{case}_abicc_report.html")


# ── Main ──────────────────────────────────────────────────────────────────────
def _col(v: str) -> str:
    colors = {"BREAKING": "\033[91m", "COMPATIBLE": "\033[93m",
              "NO_CHANGE": "\033[92m", "ERROR": "\033[95m", "SKIP": "\033[90m",
              "TIMEOUT": "\033[95m"}
    return f"{colors.get(v,'')}{v:<12}\033[0m"


def _best_h(ver: str, bdir_h: Path, case_dir: Path) -> Path:
    if bdir_h.exists():
        return bdir_h
    for ext in (".h", ".hpp"):
        p = case_dir / f"{ver}{ext}"
        if p.exists():
            return p
    return bdir_h  # may not exist — callers handle missing gracefully


def _resolve_headers_dir(case_dir: Path, eff_v1_h: Path, eff_v2_h: Path) -> Path | None:
    has_case_headers = any(case_dir.glob("*.h")) or any(case_dir.glob("*.hpp"))
    if has_case_headers:
        return case_dir
    if eff_v1_h.exists():
        return eff_v1_h.parent
    if eff_v2_h.exists():
        return eff_v2_h.parent
    return None


def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(exist_ok=True)

    cases = sorted(
        d for d in EXAMPLES_DIR.iterdir()
        if d.is_dir() and ((d / "v1.c").exists() or (d / "v1.cpp").exists())
    )

    results: list[dict] = []

    print(f"\n{'Case':<35} {'abicheck':<14} {'abidiff':<14} {'abidiff+hdr':<14} {'ABICC':<14} agree?")
    print("─" * 104)

    for case_dir in cases:
        name = case_dir.name
        ext  = ".cpp" if (case_dir / "v1.cpp").exists() else ".c"
        v1_src = case_dir / f"v1{ext}"
        v2_src = case_dir / f"v2{ext}"

        rdir = REPORT_DIR / name
        rdir.mkdir(exist_ok=True)
        bdir = BUILD_DIR / name
        bdir.mkdir(exist_ok=True)

        # case04: no v2 → copy v1 (no change)
        if not v2_src.exists():
            v2_src = v1_src

        v1_so = bdir / "lib_v1.so"
        v2_so = bdir / "lib_v2.so"
        v1_h  = bdir / "v1.h"
        v2_h  = bdir / "v2.h"

        if not compile_so(v1_src, v1_so) or not compile_so(v2_src, v2_so):
            print(f"  {name:<33} COMPILE_ERR")
            continue

        make_header(v1_src, v1_h)
        make_header(v2_src, v2_h)

        # For ABICC/abicheck: prefer explicit headers in case dir over generated ones
        # (make_header copies them to bdir; if not present, pass case_dir .h/.hpp directly)
        eff_v1_h = _best_h("v1", v1_h, case_dir)
        eff_v2_h = _best_h("v2", v2_h, case_dir)

        ac = run_abicheck(v1_so, v2_so, eff_v1_h, eff_v2_h, name, rdir)
        ab = run_abidiff(v1_so, v2_so, name, rdir)

        headers_dir = _resolve_headers_dir(case_dir, eff_v1_h, eff_v2_h)
        ab_hdr = run_abidiff(v1_so, v2_so, name, rdir, headers_dir=headers_dir, suffix="_headers")

        acc = run_abicc(v1_so, v2_so, eff_v1_h, eff_v2_h, name, rdir)

        verdicts = {ac.verdict, ab.verdict, ab_hdr.verdict, acc.verdict} - {"SKIP", "ERROR", "TIMEOUT"}
        agree = "✅" if len(verdicts) <= 1 else (
            "~" if ac.verdict in (ab.verdict, ab_hdr.verdict, acc.verdict) else "❌")

        print(
            f"  {name:<33} {_col(ac.verdict)} {_col(ab.verdict)} {_col(ab_hdr.verdict)} {_col(acc.verdict)} {agree}"
        )

        results.append({"case": name,
                        "abicheck": ac.verdict,
                        "abidiff": ab.verdict,
                        "abidiff_headers": ab_hdr.verdict,
                        "abicc": acc.verdict,
                        "abicheck_changes": ac.changes,
                        "abidiff_changes": ab.changes,
                        "abidiff_headers_changes": ab_hdr.changes,
                        "abicc_changes": acc.changes})

    # ── Summary ──
    total = len(results)

    def skip(r: dict[str, str]) -> bool:
        blocked = {"SKIP", "TIMEOUT", "ERROR"}
        return any(r[k] in blocked for k in ("abicheck", "abidiff", "abidiff_headers", "abicc"))

    valid = [r for r in results if not skip(r)]
    n = len(valid)

    all4 = sum(1 for r in valid if r["abicheck"] == r["abidiff"] == r["abidiff_headers"] == r["abicc"])
    ac_ab = sum(1 for r in valid if r["abicheck"] == r["abidiff"])
    ac_abh = sum(1 for r in valid if r["abicheck"] == r["abidiff_headers"])
    ac_acc = sum(1 for r in valid if r["abicheck"] == r["abicc"])
    ab_abh = sum(1 for r in valid if r["abidiff"] == r["abidiff_headers"])
    abh_acc = sum(1 for r in valid if r["abidiff_headers"] == r["abicc"])

    print("\n" + "─" * 104)
    print(f"  Total cases: {total}   (valid for comparison: {n})")
    print(f"  All four agree:              {all4}/{n} ({100*all4//n if n else 0}%)")
    print(f"  abicheck == abidiff:         {ac_ab}/{n}")
    print(f"  abicheck == abidiff+hdr:     {ac_abh}/{n}")
    print(f"  abicheck == ABICC:           {ac_acc}/{n}")
    print(f"  abidiff == abidiff+hdr:      {ab_abh}/{n}")
    print(f"  abidiff+hdr == ABICC:        {abh_acc}/{n}")

    # Divergences
    divs = [
        r for r in valid
        if not (r["abicheck"] == r["abidiff"] == r["abidiff_headers"] == r["abicc"])
    ]
    if divs:
        print("\n  Divergences:")
        for r in divs:
            print(
                f"    {r['case']:<33} "
                f"ac={r['abicheck']} ab={r['abidiff']} ab+h={r['abidiff_headers']} abicc={r['abicc']}"
            )

    summary = REPORT_DIR / "comparison_summary.json"
    summary.write_text(json.dumps(results, indent=2))
    print(f"\n  Reports: {REPORT_DIR}/")
    print(f"  Summary: {summary}")


if __name__ == "__main__":
    main()
