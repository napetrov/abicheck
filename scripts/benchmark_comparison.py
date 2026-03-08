#!/usr/bin/env python3
"""
Benchmark: abicheck vs ABICC vs abidiff on abicheck examples.

Runs all three tools on each example pair (v1/v2) and prints a comparison table.
abidiff is run twice: without headers (ELF-only) and with --headers-dir.

Two ABICC modes are supported:
  - abicc_xml:    legacy XML descriptor (no abi-dumper, fast but inaccurate)
  - abicc_dumper: proper abi-dumper workflow (compile with -g, dump ABI, compare)

Usage:
    python3 scripts/benchmark_comparison.py
    python3 scripts/benchmark_comparison.py --abicc-timeout 60
    python3 scripts/benchmark_comparison.py --abicc-mode dumper
    python3 scripts/benchmark_comparison.py --skip-abicc
"""
from __future__ import annotations

import argparse
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

DEFAULT_ABICC_TIMEOUT = 30  # seconds; was 120 in legacy code


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
        [compiler, "-shared", "-fPIC", "-g", "-Og", "-fvisibility=default",
         "-o", str(out_so), str(src)],
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
    return bdir_h


def _resolve_headers_dir(case_dir: Path, v1_h: Path, v2_h: Path) -> str | None:
    """Return the most useful --headers-dir for abidiff, or None."""
    if v1_h.exists():
        return str(v1_h.parent)
    return None


# ── abicheck ──────────────────────────────────────────────────────────────────
def run_abicheck(v1_so: Path, v2_so: Path, v1_h: Path, v2_h: Path,
                 case: str, rdir: Path) -> ToolResult:
    if not shutil.which("abicheck"):
        return ToolResult(verdict="SKIP")

    cmd = ["abicheck", "compare", str(v1_so), str(v2_so)]
    if v1_h.exists():
        cmd += ["--headers", str(v1_h)]
    if v2_h.exists():
        cmd += ["--new-headers", str(v2_h)]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    (rdir / f"{case}_abicheck.txt").write_text(out)

    if r.returncode == 2:
        verdict = "BREAKING"
    elif r.returncode == 1:
        verdict = "COMPATIBLE"
    elif r.returncode == 0:
        verdict = "NO_CHANGE"
    else:
        verdict = "ERROR"

    changes = [ln.strip() for ln in out.splitlines()
               if any(k in ln for k in ("removed", "added", "changed")) and ln.strip()]
    return ToolResult(verdict=verdict, changes=changes[:8], raw_output=out)


# ── abidiff ───────────────────────────────────────────────────────────────────
def run_abidiff(v1_so: Path, v2_so: Path, case: str, rdir: Path,
                headers_dir: str | None = None,
                suffix: str = "") -> ToolResult:
    if not shutil.which("abidiff"):
        return ToolResult(verdict="SKIP")

    cmd = ["abidiff"]
    if headers_dir:
        cmd += ["--headers-dir", headers_dir]
    cmd += [str(v1_so), str(v2_so)]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    (rdir / f"{case}_abidiff{suffix}.txt").write_text(out)

    # abidiff exit codes: 0=no change, 4=compatible change, 8=incompatible (ABI breaking)
    if r.returncode & 8:
        verdict = "BREAKING"
    elif r.returncode & 4:
        verdict = "COMPATIBLE"
    elif r.returncode == 0:
        verdict = "NO_CHANGE"
    else:
        verdict = "ERROR"

    changes = [ln.strip() for ln in out.splitlines()
               if any(k in ln for k in ("removed", "added", "changed")) and ln.strip()]
    return ToolResult(verdict=verdict, changes=changes[:8], raw_output=out)


# ── ABICC (legacy XML descriptor) ─────────────────────────────────────────────
def run_abicc_xml(v1_so: Path, v2_so: Path, v1_h: Path, v2_h: Path,
                  case: str, rdir: Path, timeout: int = DEFAULT_ABICC_TIMEOUT) -> ToolResult:
    """Legacy mode: XML descriptor pointing at .so directly (no abi-dumper).

    Fast but inaccurate — ABICC without GCC dump misses most type-level changes.
    Use run_abicc_dumper() for accurate results.
    """
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

    html_out = rdir / f"{case}_abicc_xml_report.html"
    try:
        r = subprocess.run(
            ["abi-compliance-checker", "-l", case,
             "-old", str(v1_xml), "-new", str(v2_xml),
             "-report-path", str(html_out)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(verdict="TIMEOUT")

    out = r.stdout + r.stderr
    (rdir / f"{case}_abicc_xml.txt").write_text(out)

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
                      report_path=f"{case}_abicc_xml_report.html")


# ── ABICC (abi-dumper workflow) ────────────────────────────────────────────────
def run_abicc_dumper(v1_so: Path, v2_so: Path, v1_h: Path, v2_h: Path,
                     case: str, rdir: Path,
                     timeout: int = DEFAULT_ABICC_TIMEOUT) -> ToolResult:
    """Proper ABICC mode: compile with -g -Og, dump ABI via abi-dumper, then compare.

    This is the recommended workflow for ABICC. abi-dumper extracts full type
    information from DWARF debug data, producing an ABI descriptor that ABICC
    can accurately diff — no GCC fdump-lang-spec needed.

    Steps:
      1. abi-dumper <lib.so> -o dump.abi -lver
      2. abi-compliance-checker -l <lib> -old dump1.abi -new dump2.abi
    """
    if not shutil.which("abi-compliance-checker"):
        return ToolResult(verdict="SKIP")
    if not shutil.which("abi-dumper"):
        return ToolResult(verdict="SKIP")

    dump_v1 = rdir / f"{case}_v1.abi"
    dump_v2 = rdir / f"{case}_v2.abi"

    # Step 1: generate ABI dumps
    for so, dump, ver in [(v1_so, dump_v1, "v1"), (v2_so, dump_v2, "v2")]:
        dump_cmd = ["abi-dumper", str(so), "-o", str(dump), "-lver", ver]
        if v1_h.exists():
            dump_cmd += ["-public-headers", str(v1_h.parent)]
        try:
            dr = subprocess.run(
                dump_cmd, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(verdict="TIMEOUT", raw_output=f"abi-dumper timeout on {ver}")
        if dr.returncode != 0 or not dump.exists():
            err = dr.stderr[:200] if dr.stderr else "no dump produced"
            return ToolResult(verdict="ERROR", raw_output=f"abi-dumper failed ({ver}): {err}")

    # Step 2: compare dumps
    html_out = rdir / f"{case}_abicc_dumper_report.html"
    try:
        r = subprocess.run(
            ["abi-compliance-checker", "-l", case,
             "-old", str(dump_v1), "-new", str(dump_v2),
             "-report-path", str(html_out)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(verdict="TIMEOUT")

    out = r.stdout + r.stderr
    (rdir / f"{case}_abicc_dumper.txt").write_text(out)

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
                      report_path=f"{case}_abicc_dumper_report.html")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _col(v: str) -> str:
    colors = {"BREAKING": "\033[91m", "COMPATIBLE": "\033[93m",
              "NO_CHANGE": "\033[92m", "ERROR": "\033[95m", "SKIP": "\033[90m",
              "TIMEOUT": "\033[95m"}
    return f"{colors.get(v, '')}{v:<12}\033[0m"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark abicheck vs abidiff vs ABICC")
    p.add_argument(
        "--abicc-timeout", type=int, default=DEFAULT_ABICC_TIMEOUT, metavar="N",
        help=f"Timeout in seconds for each ABICC invocation (default: {DEFAULT_ABICC_TIMEOUT})",
    )
    p.add_argument(
        "--abicc-mode", choices=["xml", "dumper", "both"], default="dumper",
        help="ABICC analysis mode: xml (legacy), dumper (proper), or both (default: dumper)",
    )
    p.add_argument(
        "--skip-abicc", action="store_true",
        help="Skip ABICC entirely (useful in CI environments where it's not installed)",
    )
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()

    REPORT_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(exist_ok=True)

    cases = sorted(
        d for d in EXAMPLES_DIR.iterdir()
        if d.is_dir() and ((d / "v1.c").exists() or (d / "v1.cpp").exists())
    )

    results: list[dict[str, object]] = []

    use_dumper = not args.skip_abicc and args.abicc_mode in ("dumper", "both")
    use_xml    = not args.skip_abicc and args.abicc_mode in ("xml", "both")

    # Build header
    col_headers = f"{'Case':<35} {'abicheck':<14} {'abidiff':<14} {'abidiff+hdr':<14}"
    if use_dumper:
        col_headers += f" {'ABICC(dumper)':<16}"
    if use_xml:
        col_headers += f" {'ABICC(xml)':<14}"
    col_headers += " agree?"
    width = len(col_headers)
    print(f"\n{col_headers}")
    print("─" * max(width, 80))

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

        # For ABICC/abicheck: prefer explicit headers in case dir over generated ones
        eff_v1_h = _best_h("v1", v1_h, case_dir)
        eff_v2_h = _best_h("v2", v2_h, case_dir)

        ac     = run_abicheck(v1_so, v2_so, eff_v1_h, eff_v2_h, name, rdir)
        ab     = run_abidiff(v1_so, v2_so, name, rdir)

        headers_dir = _resolve_headers_dir(case_dir, eff_v1_h, eff_v2_h)
        ab_hdr = run_abidiff(v1_so, v2_so, name, rdir,
                             headers_dir=headers_dir, suffix="_headers")

        acc_dumper = (run_abicc_dumper(v1_so, v2_so, eff_v1_h, eff_v2_h, name, rdir,
                                       timeout=args.abicc_timeout)
                      if use_dumper else ToolResult(verdict="SKIP"))
        acc_xml    = (run_abicc_xml(v1_so, v2_so, eff_v1_h, eff_v2_h, name, rdir,
                                    timeout=args.abicc_timeout)
                      if use_xml else ToolResult(verdict="SKIP"))

        all_verdicts = {ac.verdict, ab.verdict, ab_hdr.verdict,
                        acc_dumper.verdict, acc_xml.verdict} - {"SKIP", "ERROR", "TIMEOUT"}
        agree = "✅" if len(all_verdicts) <= 1 else (
            "~" if ac.verdict in (ab.verdict, ab_hdr.verdict,
                                   acc_dumper.verdict, acc_xml.verdict) else "❌")

        row = f"  {name:<33} {_col(ac.verdict)} {_col(ab.verdict)} {_col(ab_hdr.verdict)}"
        if use_dumper:
            row += f" {_col(acc_dumper.verdict):<16}"
        if use_xml:
            row += f" {_col(acc_xml.verdict)}"
        row += f" {agree}"
        print(row)

        results.append({
            "case":                    name,
            "abicheck":                ac.verdict,
            "abidiff":                 ab.verdict,
            "abidiff_headers":         ab_hdr.verdict,
            "abicc_dumper":            acc_dumper.verdict,
            "abicc_xml":               acc_xml.verdict,
            "abicheck_changes":        ac.changes,
            "abidiff_changes":         ab.changes,
            "abidiff_headers_changes": ab_hdr.changes,
            "abicc_dumper_changes":    acc_dumper.changes,
            "abicc_xml_changes":       acc_xml.changes,
        })

    # ── Summary ──────────────────────────────────────────────────────────────
    total = len(results)

    def _skip(r: dict[str, object], key: str) -> bool:
        return r[key] in {"SKIP", "TIMEOUT", "ERROR"}

    def _valid_pair(r: dict[str, object], k1: str, k2: str) -> bool:
        return not (_skip(r, k1) or _skip(r, k2))

    valid_ac_ab   = [r for r in results if _valid_pair(r, "abicheck", "abidiff")]
    valid_ac_abh  = [r for r in results if _valid_pair(r, "abicheck", "abidiff_headers")]
    valid_ac_dump = [r for r in results if _valid_pair(r, "abicheck", "abicc_dumper")]
    valid_ac_xml  = [r for r in results if _valid_pair(r, "abicheck", "abicc_xml")]
    valid_all     = [r for r in results
                     if not any(_skip(r, k) for k in
                                ("abicheck", "abidiff", "abidiff_headers",
                                 "abicc_dumper", "abicc_xml"))]

    n = len(valid_all)

    print("\n" + "─" * max(width, 80))
    print(f"  Total cases: {total}")

    if valid_ac_ab:
        n_ab = len(valid_ac_ab)
        s = sum(1 for r in valid_ac_ab if r["abicheck"] == r["abidiff"])
        print(f"  abicheck == abidiff:          {s}/{n_ab}")

    if valid_ac_abh:
        n_abh = len(valid_ac_abh)
        s = sum(1 for r in valid_ac_abh if r["abicheck"] == r["abidiff_headers"])
        print(f"  abicheck == abidiff+hdr:      {s}/{n_abh}")

    if valid_ac_dump:
        n_d = len(valid_ac_dump)
        s = sum(1 for r in valid_ac_dump if r["abicheck"] == r["abicc_dumper"])
        print(f"  abicheck == ABICC(dumper):    {s}/{n_d}")

    if valid_ac_xml:
        n_x = len(valid_ac_xml)
        s = sum(1 for r in valid_ac_xml if r["abicheck"] == r["abicc_xml"])
        print(f"  abicheck == ABICC(xml):       {s}/{n_x}")

    if n:
        all5 = sum(
            1 for r in valid_all
            if r["abicheck"] == r["abidiff"] == r["abidiff_headers"]
            == r["abicc_dumper"] == r["abicc_xml"]
        )
        print(f"  All five agree:               {all5}/{n}")

    # Divergences
    divs = [
        r for r in results
        if not _skip(r, "abicheck")
        and not all(
            _skip(r, k) or r[k] == r["abicheck"]
            for k in ("abidiff", "abidiff_headers", "abicc_dumper", "abicc_xml")
        )
    ]
    if divs:
        print("\n  Divergences:")
        for r in divs:
            parts = [f"ac={r['abicheck']}"]
            if not _skip(r, "abidiff"):
                parts.append(f"ab={r['abidiff']}")
            if not _skip(r, "abidiff_headers"):
                parts.append(f"ab+h={r['abidiff_headers']}")
            if not _skip(r, "abicc_dumper"):
                parts.append(f"abicc_d={r['abicc_dumper']}")
            if not _skip(r, "abicc_xml"):
                parts.append(f"abicc_x={r['abicc_xml']}")
            print(f"    {r['case']:<33} {' '.join(parts)}")

    summary = REPORT_DIR / "comparison_summary.json"
    summary.write_text(json.dumps(results, indent=2))
    print(f"\n  Reports: {REPORT_DIR}/")
    print(f"  Summary: {summary}")


if __name__ == "__main__":
    main()
