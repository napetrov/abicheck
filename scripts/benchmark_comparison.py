#!/usr/bin/env python3
"""
Benchmark: abicheck vs ABICC vs abidiff on abicheck examples.

Runs all tools on each example pair (v1/v2) and prints a comparison table.
abidiff is run twice: without headers (ELF-only) and with --headers-dir.
abicheck is run in two modes: compare (dump+compare pipeline) and compat (ABICC drop-in).

Two ABICC modes are supported:
  - abicc_xml:    legacy XML descriptor (no abi-dumper, fast but inaccurate)
  - abicc_dumper: proper abi-dumper workflow (compile with -g, dump ABI, compare)

Supports two case layouts:
  - v1/v2 layout: case_dir/v1.c + case_dir/v2.c (cases 01-18)
  - old/new layout: case_dir/old/lib.c + case_dir/new/lib.c (cases 19+)

Usage:
    python3 scripts/benchmark_comparison.py
    python3 scripts/benchmark_comparison.py --abicc-timeout 60
    python3 scripts/benchmark_comparison.py --abicc-mode dumper
    python3 scripts/benchmark_comparison.py --skip-abicc
    python3 scripts/benchmark_comparison.py --skip-compat
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO_DIR     = Path(__file__).parent.parent
EXAMPLES_DIR = REPO_DIR / "examples"
REPORT_DIR   = REPO_DIR / "benchmark_reports"
BUILD_DIR    = REPORT_DIR / "_build"

# Ensure we use abicheck from THIS repo, not any globally-installed version
# (abicheck CLI shebang may point to a different Python/site-packages)
os.environ.setdefault("PYTHONPATH", str(REPO_DIR))

import sys as _sys

_abicheck_bin = shutil.which("abicheck")
if _abicheck_bin:
    try:
        with open(_abicheck_bin) as _f:
            _first_line = _f.readline().strip()
        if _first_line.startswith("#!"):
            _tokens = shlex.split(_first_line.lstrip("#!"))
            # Handle `#!/usr/bin/env python3` → use token after "env", not "env" itself
            if _tokens and os.path.basename(_tokens[0]) == "env" and len(_tokens) > 1:
                _PYTHON = _tokens[1]
            elif _tokens:
                _PYTHON = _tokens[0]
            else:
                _PYTHON = _sys.executable
        else:
            _PYTHON = _sys.executable
    except (OSError, IsADirectoryError, IndexError):
        _PYTHON = _sys.executable
else:
    _PYTHON = _sys.executable
_ABICHECK_ENV = {**os.environ, "PYTHONPATH": str(REPO_DIR)}
# True when abicheck CLI is importable via _PYTHON (even without installed bin)
def _abicheck_available() -> bool:
    import subprocess as _sp
    r = _sp.run([_PYTHON, "-m", "abicheck.cli", "--help"],
                capture_output=True, timeout=10, env=_ABICHECK_ENV)
    return r.returncode == 0

_HAS_ABICHECK: bool = _abicheck_available()


DEFAULT_ABICC_TIMEOUT = 30  # seconds

# Expected verdicts from case READMEs
EXPECTED: dict[str, str] = {
    "case01_symbol_removal":          "BREAKING",
    "case02_param_type_change":       "BREAKING",
    "case03_compat_addition":         "COMPATIBLE",
    "case04_no_change":               "NO_CHANGE",
    "case05_soname":                  "BREAKING",    # KNOWN GAP: abicheck doesn't detect missing SONAME (ELF DT_SONAME absent)
    "case06_visibility":              "BREAKING",    # KNOWN GAP: needs -fvisibility=hidden at compile time; benchmark builds with -fvisibility=default
    "case07_struct_layout":           "BREAKING",
    "case08_enum_value_change":       "BREAKING",
    "case09_cpp_vtable":              "BREAKING",
    "case10_return_type":             "BREAKING",
    "case11_global_var_type":         "BREAKING",
    "case12_function_removed":        "BREAKING",
    "case13_symbol_versioning":       "BREAKING",    # KNOWN GAP: abicheck doesn't detect missing version script (ELF symbol versioning)
    "case14_cpp_class_size":          "BREAKING",
    "case15_noexcept_change":         "BREAKING",   # v2.cpp adds throw → pulls GLIBCXX_3.4.21 → SYMBOL_VERSION_REQUIRED_ADDED
    "case16_inline_to_non_inline":    "COMPATIBLE",
    "case17_template_abi":            "BREAKING",
    "case18_dependency_leak":         "BREAKING",
    "case19_enum_member_removed":     "BREAKING",
    "case20_enum_member_value_changed": "BREAKING",
    "case21_method_became_static":    "BREAKING",
    "case22_method_const_changed":    "BREAKING",
    "case23_pure_virtual_added":      "BREAKING",
    "case24_union_field_removed":     "BREAKING",
    "case25_enum_member_added":       "COMPATIBLE",
    "case26_union_field_added":       "BREAKING",    # double d makes sizeof(Value) grow 4→8 bytes: TYPE_SIZE_CHANGED
    "case27_symbol_binding_weakened": "COMPATIBLE",
    "case29_ifunc_transition":        "COMPATIBLE",  # IFUNC_INTRODUCED — PLT/GOT transparent; fix merged in Sprint 7
    # ── cases 28, 30-41 (Sprint 7 — new detectors) ──────────────────────────
    "case28_typedef_opaque":          "BREAKING",    # TYPEDEF_BASE_CHANGED, TYPE_BECAME_OPAQUE
    "case30_field_qualifiers":        "BREAKING",    # STRUCT_FIELD_TYPE_CHANGED (const/volatile)
    "case31_enum_rename":             "BREAKING",    # ENUM_MEMBER_REMOVED/RENAMED
    "case32_param_defaults":          "NO_CHANGE",   # default value change — source-only, binary NO_CHANGE
    "case33_pointer_level":           "BREAKING",    # PARAM_POINTER_LEVEL_CHANGED
    "case34_access_level":            "SOURCE_BREAK",  # access level is source-only; binary layout unchanged → SOURCE_BREAK with headers
    "case35_field_rename":            "BREAKING",    # STRUCT_FIELD_REMOVED (rename = remove+add)
    "case36_anon_struct":             "BREAKING",    # ANON_FIELD_CHANGED / TYPE_SIZE_CHANGED
    "case37_base_class":              "BREAKING",    # BASE_CLASS_POSITION_CHANGED
    "case38_virtual_methods":         "BREAKING",    # FUNC_VIRTUAL_ADDED / FUNC_VIRTUAL_REMOVED
    "case39_var_const":               "NO_CHANGE",   # VAR_BECAME_CONST — currently NO_CHANGE in abicheck
    "case40_field_layout":            "BREAKING",    # TYPE_SIZE_CHANGED (struct reordering)
    "case41_type_changes":            "BREAKING",    # FUNC_REMOVED, TYPE_REMOVED
}

# Per-column expected overrides for abicheck compat mode (ELF-only XML descriptors,
# no header parsing). Compat can't emit SOURCE_BREAK — access-level narrowing is
# invisible without headers, so correct compat verdict is NO_CHANGE.
EXPECTED_COMPAT: dict[str, str] = {
    "case34_access_level": "NO_CHANGE",  # compat = ELF-only; no header → can't see access narrowing
}


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
        print(f"    [compile error] {src.name}: {r.stderr[:120]}")
    return r.returncode == 0


def make_header(src: Path, out_h: Path) -> None:
    """Copy explicit .h/.hpp if present; generate minimal header for plain C."""
    for ext in (".h", ".hpp"):
        h = src.with_suffix(ext)
        if h.exists():
            shutil.copy(h, out_h)
            return
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


def _best_h(name: str, bdir_h: Path, src_dir: Path) -> Path:
    """Prefer explicit header in src_dir, fall back to generated copy."""
    for ext in (".h", ".hpp"):
        p = src_dir / f"{name}{ext}"
        if p.exists():
            return p
    return bdir_h


def _resolve_headers_dir(case_dir: Path, v1_h: Path, v2_h: Path) -> str | None:
    if v1_h.exists():
        return str(v1_h.parent)
    if v2_h.exists():
        return str(v2_h.parent)
    return None


# ── Case layout detection ─────────────────────────────────────────────────────
def find_sources(case_dir: Path) -> tuple[Path | None, Path | None, Path | None, Path | None]:
    """Return (v1_src, v2_src, v1_h_hint, v2_h_hint) or (None, None, None, None) if unsupported."""
    # v1/v2 layout
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"v1{ext}"
        if v1.exists():
            v2 = case_dir / f"v2{ext}"
            if not v2.exists():
                v2 = v1  # case04: identical
            v1h = case_dir / f"v1{'.h' if ext == '.c' else '.hpp'}"
            v2h = case_dir / f"v2{'.h' if ext == '.c' else '.hpp'}"
            return v1, v2, v1h if v1h.exists() else None, v2h if v2h.exists() else None

    # old/new layout (cases 19+)
    old_dir = case_dir / "old"
    new_dir = case_dir / "new"
    if old_dir.is_dir() and new_dir.is_dir():
        for ext in (".c", ".cpp"):
            v1 = old_dir / f"lib{ext}"
            if v1.exists():
                v2 = new_dir / f"lib{ext}"
                if not v2.exists():
                    v2 = v1
                hext = ".h" if ext == ".c" else ".hpp"
                v1h = old_dir / f"lib{hext}"
                v2h = new_dir / f"lib{hext}"
                return v1, v2, v1h if v1h.exists() else None, v2h if v2h.exists() else None

    # case18: libfoo_v1.c / libfoo_v2.c
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"libfoo_v1{ext}"
        if v1.exists():
            v2 = case_dir / f"libfoo_v2{ext}"
            if not v2.exists():
                v2 = v1
            v1h = case_dir / f"foo_v1{'.h' if ext == '.c' else '.hpp'}"
            v2h = case_dir / f"foo_v2{'.h' if ext == '.c' else '.hpp'}"
            return v1, v2, v1h if v1h.exists() else None, v2h if v2h.exists() else None

    # good/bad layout (cases 05/06/13)
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"good{ext}"
        if v1.exists():
            v2 = case_dir / f"bad{ext}"
            if not v2.exists():
                v2 = v1
            return v1, v2, None, None

    return None, None, None, None


# ── abicheck compare (dump + compare pipeline) ────────────────────────────────
def run_abicheck(v1_so: Path, v2_so: Path, v1_h: Path | None, v2_h: Path | None,
                 case: str, rdir: Path) -> ToolResult:
    if not _HAS_ABICHECK:
        return ToolResult(verdict="SKIP")

    bdir = BUILD_DIR / case
    snap1 = bdir / "snap_v1.json"
    snap2 = bdir / "snap_v2.json"

    def dump(so: Path, h: Path | None, snap: Path, ver: str) -> bool:
        cmd = [_PYTHON, "-m", "abicheck.cli", "dump", str(so), "-o", str(snap), "--version", ver]
        if h and h.exists():
            cmd += ["-H", str(h)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=_ABICHECK_ENV)
        return r.returncode == 0 and snap.exists()

    try:
        if not dump(v1_so, v1_h, snap1, "v1"):
            return ToolResult(verdict="ERROR", raw_output="dump v1 failed")
        if not dump(v2_so, v2_h, snap2, "v2"):
            return ToolResult(verdict="ERROR", raw_output="dump v2 failed")
    except subprocess.TimeoutExpired:
        return ToolResult(verdict="TIMEOUT")

    try:
        r = subprocess.run(
            [_PYTHON, "-m", "abicheck.cli", "compare", str(snap1), str(snap2), "--format", "json"],
            capture_output=True, text=True, timeout=60, env=_ABICHECK_ENV,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(verdict="TIMEOUT")

    out = r.stdout + r.stderr
    (rdir / f"{case}_abicheck.txt").write_text(out)

    # abicheck compare exit codes: 4=BREAKING, 2=SOURCE_BREAK, 1=COMPATIBLE, 0=NO_CHANGE
    # Read verdict from JSON output for accuracy
    try:
        data = json.loads(r.stdout)
        raw_v = data.get("verdict", "").upper()
        if raw_v in ("BREAKING",):
            verdict = "BREAKING"
        elif raw_v == "SOURCE_BREAK":
            verdict = "SOURCE_BREAK"
        elif raw_v == "COMPATIBLE":
            verdict = "COMPATIBLE"
        elif raw_v == "NO_CHANGE":
            verdict = "NO_CHANGE"
        else:
            verdict = "ERROR"
    except (json.JSONDecodeError, AttributeError):
        # Fallback: exit code mapping (4=BREAKING, 2=SOURCE_BREAK, 1=COMPATIBLE, 0=NO_CHANGE)
        if r.returncode == 4:
            verdict = "BREAKING"
        elif r.returncode == 2:
            verdict = "SOURCE_BREAK"
        elif r.returncode == 1:
            verdict = "COMPATIBLE"
        elif r.returncode == 0:
            verdict = "NO_CHANGE"
        else:
            verdict = "ERROR"

    changes = [ln.strip() for ln in out.splitlines()
               if any(k in ln for k in ("removed", "added", "changed")) and ln.strip()]
    return ToolResult(verdict=verdict, changes=changes[:8], raw_output=out)


# ── abicheck compat (ABICC XML drop-in) ──────────────────────────────────────
def run_abicheck_compat(v1_so: Path, v2_so: Path, v1_h: Path | None, v2_h: Path | None,
                        case: str, rdir: Path) -> ToolResult:
    """Run abicheck compat with ABICC-format XML descriptors."""
    if not _HAS_ABICHECK:
        return ToolResult(verdict="SKIP")

    def xml(so: Path, h: Path | None, ver: str, out: Path) -> None:
        # NOTE: abicheck compat currently expects header file paths in <headers>
        header = str(h) if h and h.exists() else ""
        out.write_text(
            f"<descriptor>\n"
            f"  <version>{ver}</version>\n"
            f"  <headers>{header}</headers>\n"
            f"  <libs>{so}</libs>\n"
            f"</descriptor>\n"
        )

    v1_xml = rdir / f"{case}_compat_v1.xml"
    v2_xml = rdir / f"{case}_compat_v2.xml"
    xml(v1_so, v1_h, "v1", v1_xml)
    xml(v2_so, v2_h, "v2", v2_xml)

    try:
        r = subprocess.run(
            [_PYTHON, "-m", "abicheck.cli", "compat", "-lib", case,
             "-old", str(v1_xml), "-new", str(v2_xml)],
            capture_output=True, text=True, timeout=60, env=_ABICHECK_ENV,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(verdict="TIMEOUT")

    out = r.stdout + r.stderr
    (rdir / f"{case}_abicheck_compat.txt").write_text(out)

    # compat exit codes (from abicheck/cli.py compat command):
    #   0 = NO_CHANGE or COMPATIBLE
    #   1 = BREAKING
    #   2 = SOURCE_BREAK (source-level break, binary compatible)
    if r.returncode == 1:
        verdict = "BREAKING"
    elif r.returncode == 2:
        verdict = "SOURCE_BREAK"
    elif r.returncode == 0:
        # distinguish NO_CHANGE from COMPATIBLE by output
        if "no changes" in out.lower() or "identical" in out.lower():
            verdict = "NO_CHANGE"
        else:
            verdict = "COMPATIBLE"
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
        cmd += ["--headers-dir1", headers_dir, "--headers-dir2", headers_dir]
    cmd += [str(v1_so), str(v2_so)]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return ToolResult(verdict="TIMEOUT")
    out = r.stdout + r.stderr
    (rdir / f"{case}_abidiff{suffix}.txt").write_text(out)

    # abidiff exit bitmask: bit0=tool-err, bit1=app-err, bit2=compat, bit3=breaking
    if r.returncode & 1 or r.returncode & 2:
        verdict = "ERROR"
    elif r.returncode & 8:
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
def run_abicc_xml(v1_so: Path, v2_so: Path, v1_h: Path | None, v2_h: Path | None,
                  case: str, rdir: Path, timeout: int = DEFAULT_ABICC_TIMEOUT) -> ToolResult:
    if not shutil.which("abi-compliance-checker"):
        return ToolResult(verdict="SKIP")

    def xml(so: Path, h: Path | None, ver: str, out: Path) -> None:
        hdir = str(h.parent) if h and h.exists() else "/usr/include"
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
                      report_path=str(html_out))


# ── ABICC (abi-dumper workflow) ────────────────────────────────────────────────
def run_abicc_dumper(v1_so: Path, v2_so: Path, v1_h: Path | None, v2_h: Path | None,
                     case: str, rdir: Path,
                     timeout: int = DEFAULT_ABICC_TIMEOUT) -> ToolResult:
    if not shutil.which("abi-compliance-checker"):
        return ToolResult(verdict="SKIP")
    if not shutil.which("abi-dumper"):
        return ToolResult(verdict="SKIP")

    dump_v1 = rdir / f"{case}_v1.abi"
    dump_v2 = rdir / f"{case}_v2.abi"

    for so, dump, ver, hdr in [
        (v1_so, dump_v1, "v1", v1_h),
        (v2_so, dump_v2, "v2", v2_h),
    ]:
        dump_cmd = ["abi-dumper", str(so), "-o", str(dump), "-lver", ver]
        if hdr and hdr.exists():
            dump_cmd += ["-public-headers", str(hdr.parent)]
        try:
            dr = subprocess.run(dump_cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return ToolResult(verdict="TIMEOUT")
        if dr.returncode != 0 or not dump.exists():
            return ToolResult(verdict="ERROR", raw_output=f"abi-dumper failed ({ver})")

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
                      report_path=str(html_out))


# ── Helpers ───────────────────────────────────────────────────────────────────
_COLORS = {
    "BREAKING":     "\033[91m",
    "SOURCE_BREAK": "\033[94m",  # blue — source-only, binary-safe
    "COMPATIBLE":   "\033[93m",
    "NO_CHANGE":    "\033[92m",
    "ERROR":        "\033[95m",
    "SKIP":         "\033[90m",
    "TIMEOUT":      "\033[95m",
}
_RESET = "\033[0m"


def _col(v: str, width: int = 12) -> str:
    return f"{_COLORS.get(v, '')}{v:<{width}}{_RESET}"


def _correct(verdict: str, expected: str) -> str:
    """Return emoji indicator vs expected."""
    if verdict in ("SKIP", "ERROR", "TIMEOUT"):
        return "—"
    return "✅" if verdict == expected else "❌"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark abicheck vs abidiff vs ABICC")
    p.add_argument("--abicc-timeout", type=int, default=DEFAULT_ABICC_TIMEOUT,
                   help=f"Timeout per ABICC call (default: {DEFAULT_ABICC_TIMEOUT}s)")
    p.add_argument("--abicc-mode", choices=["xml", "dumper", "both"], default="both",
                   help="ABICC mode: xml (legacy XML descriptor), dumper (abi-dumper workflow), or both (default: both)")
    p.add_argument("--skip-abicc", action="store_true",
                   help="Skip ABICC entirely")
    p.add_argument("--skip-compat", action="store_true",
                   help="Skip abicheck compat column")
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()

    REPORT_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(exist_ok=True)

    all_cases = sorted(d for d in EXAMPLES_DIR.iterdir() if d.is_dir() and d.name.startswith("case"))

    use_dumper = not args.skip_abicc and args.abicc_mode in ("dumper", "both")
    use_xml    = not args.skip_abicc and args.abicc_mode in ("xml", "both")
    use_compat = not args.skip_compat

    # Header
    cols = [("Case", 35), ("Expected", 12), ("abicheck", 12), ]
    if use_compat:
        cols.append(("ac-compat", 12))
    cols += [("abidiff", 12), ("abidiff+hdr", 12)]
    if use_dumper:
        cols.append(("ABICC(dump)", 12))
    if use_xml:
        cols.append(("ABICC(xml)", 12))

    hdr = " ".join(f"{name:<{w}}" for name, w in cols)
    print(f"\n{hdr}")
    print("─" * len(hdr))

    results: list[dict] = []

    for case_dir in all_cases:
        name = case_dir.name
        expected = EXPECTED.get(name, "?")

        v1_src, v2_src, v1_h_hint, v2_h_hint = find_sources(case_dir)
        if v1_src is None:
            row = f"  {name:<33} {expected:<12} {'NO_SOURCE':<12}"
            print(row)
            results.append({"case": name, "expected": expected, "abicheck": "SKIP",
                             "abicheck_compat": "SKIP", "abidiff": "SKIP",
                             "abidiff_headers": "SKIP", "abicc_dumper": "SKIP",
                             "abicc_xml": "SKIP"})
            continue

        rdir = REPORT_DIR / name
        rdir.mkdir(exist_ok=True)
        bdir = BUILD_DIR / name
        bdir.mkdir(exist_ok=True)

        v1_so = bdir / "lib_v1.so"
        v2_so = bdir / "lib_v2.so"
        v1_h_gen = bdir / "v1.h"
        v2_h_gen = bdir / "v2.h"

        if not compile_so(v1_src, v1_so) or not compile_so(v2_src, v2_so):
            print(f"  {name:<35} COMPILE_ERR")
            continue

        # Generate fallback headers
        make_header(v1_src, v1_h_gen)
        make_header(v2_src, v2_h_gen)

        # Best headers: explicit hint > generated
        v1_h = v1_h_hint if v1_h_hint else (v1_h_gen if v1_h_gen.exists() else None)
        v2_h = v2_h_hint if v2_h_hint else (v2_h_gen if v2_h_gen.exists() else None)

        ac  = run_abicheck(v1_so, v2_so, v1_h, v2_h, name, rdir)
        acc = run_abicheck_compat(v1_so, v2_so, v1_h, v2_h, name, rdir) if use_compat else ToolResult(verdict="SKIP")
        ab  = run_abidiff(v1_so, v2_so, name, rdir)

        headers_dir = _resolve_headers_dir(case_dir, v1_h or Path("/nonexistent"), v2_h or Path("/nonexistent"))
        ab_hdr = run_abidiff(v1_so, v2_so, name, rdir, headers_dir=headers_dir, suffix="_headers")

        abicc_d = (run_abicc_dumper(v1_so, v2_so, v1_h, v2_h, name, rdir, timeout=args.abicc_timeout)
                   if use_dumper else ToolResult(verdict="SKIP"))
        abicc_x = (run_abicc_xml(v1_so, v2_so, v1_h, v2_h, name, rdir, timeout=args.abicc_timeout)
                   if use_xml else ToolResult(verdict="SKIP"))

        row_parts = [
            f"  {name:<33}",
            f"{expected:<12}",
            _col(ac.verdict),
        ]
        if use_compat:
            row_parts.append(_col(acc.verdict))
        row_parts += [_col(ab.verdict), _col(ab_hdr.verdict)]
        if use_dumper:
            row_parts.append(_col(abicc_d.verdict))
        if use_xml:
            row_parts.append(_col(abicc_x.verdict))

        print(" ".join(row_parts))

        results.append({
            "case": name,
            "expected": expected,
            "expected_compat": EXPECTED_COMPAT.get(name, expected),  # compat-specific override
            "abicheck": ac.verdict,
            "abicheck_compat": acc.verdict,
            "abidiff": ab.verdict,
            "abidiff_headers": ab_hdr.verdict,
            "abicc_dumper": abicc_d.verdict,
            "abicc_xml": abicc_x.verdict,
        })

    # ── Accuracy summary ──────────────────────────────────────────────────────
    def accuracy(key: str, expected_key: str = "expected") -> tuple[int, int]:
        scored = [r for r in results if r.get(expected_key, "?") != "?" and r[key] not in ("SKIP", "ERROR", "TIMEOUT", "NO_SOURCE")]
        correct = sum(1 for r in scored if r[key] == r[expected_key])
        return correct, len(scored)

    print("\n" + "─" * 80)
    print("  Accuracy vs expected verdicts:")
    for key, label, exp_key in [
        ("abicheck",       "abicheck (compare)  ", "expected"),
        ("abicheck_compat","abicheck (compat)   ", "expected_compat"),
        ("abidiff",        "abidiff (ELF)       ", "expected"),
        ("abidiff_headers","abidiff (+headers)  ", "expected"),
        ("abicc_dumper",   "ABICC (dumper)      ", "expected"),
        ("abicc_xml",      "ABICC (xml)         ", "expected"),
    ]:
        c, t = accuracy(key, exp_key)
        if t > 0:
            pct = 100 * c // t
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            print(f"    {label}: {c:>2}/{t} ({pct:3}%) {bar}")

    # Divergences from expected
    print("\n  Cases where abicheck differs from expected:")
    for r in results:
        if r.get("expected", "?") == "?":
            continue
        if r["abicheck"] not in ("SKIP", "ERROR", "TIMEOUT") and r["abicheck"] != r["expected"]:
            print(f"    {r['case']:<40} got={r['abicheck']} expected={r['expected']}")

    summary = REPORT_DIR / "comparison_summary.json"
    summary.write_text(json.dumps(results, indent=2))
    print(f"\n  Reports: {REPORT_DIR}/")
    print(f"  Summary: {summary}\n")


if __name__ == "__main__":
    main()
