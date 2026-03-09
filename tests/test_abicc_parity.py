"""ABICC parity tests.

Verifies that abicheck and abi-compliance-checker agree on ABI verdict
for canonical C/C++ library change scenarios. Tests are compiled locally
(requires gcc/g++, castxml) and compared with both tools.

Three test classes mirror the libabigail parity structure:
- test_confirmed_parity: both tools agree on verdict (full parity).
- test_abicheck_correct: abicheck detects the break; ABICC misses it.
- test_known_divergence: intentional stable divergences.

Requires: abi-compliance-checker, gcc/g++, castxml.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
import warnings
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Cases:
#   (name, src_v1, src_v2, hdr_v1, hdr_v2, lang,
#    abicheck_expected, abicc_expected, category)
#
# category values:
#   "parity"    -> both tools must agree (full parity)
#   "correct"   -> abicheck is authoritative; ABICC misses it
#   "divergence"-> intentional stable divergence
# ---------------------------------------------------------------------------
PARITY_CASES: list[tuple[str, str, str, str | None, str | None, str, str, str, str]] = [
    (
        "fn_removed",
        "int add(int a, int b) { return a + b; }\nint sub(int a, int b) { return a - b; }",
        "int add(int a, int b) { return a + b; }",
        "int add(int a, int b);\nint sub(int a, int b);",
        "int add(int a, int b);",
        "c", "BREAKING", "BREAKING", "parity",
    ),
    (
        "fn_added",
        "int add(int a, int b) { return a + b; }",
        "int add(int a, int b) { return a + b; }\nint mul(int a, int b) { return a*b; }",
        "int add(int a, int b);",
        "int add(int a, int b);\nint mul(int a, int b);",
        "c", "COMPATIBLE", "COMPATIBLE", "parity",
    ),
    (
        "no_change",
        "int add(int a, int b) { return a + b; }",
        "int add(int a, int b) { return a + b; }",
        "int add(int a, int b);",
        "int add(int a, int b);",
        "c", "NO_CHANGE", "NO_CHANGE", "parity",
    ),
    (
        "return_type",
        "int  get_val(void) { return 42; }",
        "long get_val(void) { return 42; }",
        "int  get_val(void);",
        "long get_val(void);",
        "c", "BREAKING", "BREAKING", "parity",
    ),
    (
        "param_type",
        "void set_val(int  x) { (void)x; }",
        "void set_val(long x) { (void)x; }",
        "void set_val(int  x);",
        "void set_val(long x);",
        "c", "BREAKING", "BREAKING", "parity",
    ),
    # enum value change: ABICC detects with headers
    (
        "enum_value",
        "typedef enum { RED=0, GREEN=1, BLUE=2 } Color;\n"
        "Color get_color(void) { return RED; }",
        "typedef enum { RED=0, GREEN=10, BLUE=2 } Color;\n"
        "Color get_color(void) { return RED; }",
        "typedef enum { RED=0, GREEN=1, BLUE=2 } Color;\nColor get_color(void);",
        "typedef enum { RED=0, GREEN=10, BLUE=2 } Color;\nColor get_color(void);",
        "c", "BREAKING", "BREAKING", "parity",
    ),
    # visibility change
    (
        "visibility_hidden",
        '__attribute__((visibility("default"))) int helper() { return 1; }\n'
        '__attribute__((visibility("default"))) int api()    { return helper(); }',
        '__attribute__((visibility("hidden")))  int helper() { return 1; }\n'
        '__attribute__((visibility("default"))) int api()    { return helper(); }',
        '__attribute__((visibility("default"))) int helper();\n'
        '__attribute__((visibility("default"))) int api();',
        '__attribute__((visibility("hidden")))  int helper();\n'
        '__attribute__((visibility("default"))) int api();',
        "c", "BREAKING", "BREAKING", "parity",
    ),
    # ── abicheck correct: vtable_reorder — ABICC misses in XML descriptor mode ──
    # ABICC without abi-dumper doesn't detect vtable reordering from headers+libs;
    # it reports NO_CHANGE (all zeros).  abicheck+castxml detects it as BREAKING.
    (
        "vtable_reorder",
        "struct Base {\n"
        "  virtual int foo() { return 1; }\n"
        "  virtual int bar() { return 2; }\n"
        "  virtual ~Base() {}\n"
        "};\nBase* make() { return new Base(); }",
        "struct Base {\n"
        "  virtual int bar() { return 2; }\n"
        "  virtual int foo() { return 1; }\n"
        "  virtual ~Base() {}\n"
        "};\nBase* make() { return new Base(); }",
        "struct Base { virtual int foo(); virtual int bar(); virtual ~Base(); };\n"
        "Base* make();",
        "struct Base { virtual int bar(); virtual int foo(); virtual ~Base(); };\n"
        "Base* make();",
        "cpp", "BREAKING", "NO_CHANGE", "correct",
    ),
    # ── abicheck correct: struct_size — ABICC misses in XML descriptor mode ──
    # ABICC in XML descriptor mode reports COMPATIBLE (sees field additions but
    # doesn't flag as breaking). abicheck correctly detects the layout change.
    (
        "struct_size",
        "typedef struct { int x; } Point;\n"
        "Point make_point(int x) { Point p = {x}; return p; }",
        "typedef struct { int x; int y; } Point;\n"
        "Point make_point(int x) { Point p = {x, 0}; return p; }",
        "typedef struct { int x; } Point;\nPoint make_point(int x);",
        "typedef struct { int x; int y; } Point;\nPoint make_point(int x);",
        "c", "BREAKING", "COMPATIBLE", "correct",
    ),
    # ── parity: multiple functions removed ──
    (
        "multi_fn_removed",
        "int a(void) { return 1; }\nint b(void) { return 2; }\nint c(void) { return 3; }",
        "int a(void) { return 1; }",
        "int a(void);\nint b(void);\nint c(void);",
        "int a(void);",
        "c", "BREAKING", "BREAKING", "parity",
    ),
    # ── parity: multiple functions added ──
    (
        "multi_fn_added",
        "int a(void) { return 1; }",
        "int a(void) { return 1; }\nint b(void) { return 2; }\nint c(void) { return 3; }",
        "int a(void);",
        "int a(void);\nint b(void);\nint c(void);",
        "c", "COMPATIBLE", "COMPATIBLE", "parity",
    ),
    # ── parity: enum member removed ──
    (
        "enum_member_removed",
        "typedef enum { A=0, B=1, C=2 } E;\nE get_e(void) { return A; }",
        "typedef enum { A=0, C=2 } E;\nE get_e(void) { return A; }",
        "typedef enum { A=0, B=1, C=2 } E;\nE get_e(void);",
        "typedef enum { A=0, C=2 } E;\nE get_e(void);",
        "c", "BREAKING", "BREAKING", "parity",
    ),
    # ── parity: global variable removed ──
    (
        "var_removed",
        "int api_version = 1;\nint get_version(void) { return api_version; }",
        "int get_version(void) { return 2; }",
        "extern int api_version;\nint get_version(void);",
        "int get_version(void);",
        "c", "BREAKING", "BREAKING", "parity",
    ),
]

_CONFIRMED = [c for c in PARITY_CASES if c[8] == "parity"]
_CORRECT = [c for c in PARITY_CASES if c[8] == "correct"]
_DIVERGE = [c for c in PARITY_CASES if c[8] == "divergence"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        pytest.skip(f"{name} not found in PATH")


def _compile_so(src: str, out: Path, lang: str) -> None:
    ext = ".c" if lang == "c" else ".cpp"
    src_file = out.with_suffix(ext)
    src_file.write_text(textwrap.dedent(src).strip(), encoding="utf-8")
    compiler = "gcc" if lang == "c" else "g++"
    cmd = [compiler, "-shared", "-fPIC", "-g", "-fvisibility=default",
           "-o", str(out), str(src_file)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        pytest.fail(f"Compilation failed: {r.stderr[:200]}")


def _write_abicc_descriptor(
    version: str,
    lib_path: Path,
    header_path: Path | None,
    desc_path: Path,
) -> None:
    """Write an ABICC XML descriptor file."""
    lines = [f"<version>{version}</version>"]
    if header_path is not None and header_path.exists():
        lines.append(f"<headers>{header_path}</headers>")
    lines.append(f"<libs>{lib_path}</libs>")
    desc_path.write_text("\n".join(lines), encoding="utf-8")


def _run_abicheck(
    old: Path,
    new: Path,
    hdr_v1: str | None,
    hdr_v2: str | None,
    lang: str,
    tmp_path: Path,
) -> str:
    """Run abicheck with headers when available, ELF-only otherwise."""
    try:
        from abicheck.checker import compare
        from abicheck.dumper import dump

        compiler = "cc" if lang == "c" else "c++"

        if hdr_v1 is not None:
            h1 = tmp_path / f"{old.stem}_hdr.h"
            h1.write_text(textwrap.dedent(hdr_v1).strip(), encoding="utf-8")
            headers_v1: list[Path] = [h1]
        else:
            headers_v1 = []

        if hdr_v2 is not None:
            h2 = tmp_path / f"{new.stem}_hdr.h"
            h2.write_text(textwrap.dedent(hdr_v2).strip(), encoding="utf-8")
            headers_v2: list[Path] = [h2]
        else:
            headers_v2 = []

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            old_snap = dump(old, headers=headers_v1, version="v1", compiler=compiler)
            new_snap = dump(new, headers=headers_v2, version="v2", compiler=compiler)

        result = compare(old_snap, new_snap)
        return result.verdict.value
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


def _run_abicc(
    old: Path,
    new: Path,
    hdr_v1: str | None,
    hdr_v2: str | None,
    tmp_path: Path,
) -> tuple[str, str]:
    """Run abi-compliance-checker; return (verdict, diagnostics).

    Verdict is one of BREAKING/COMPATIBLE/NO_CHANGE/ERROR(...)/TIMEOUT.
    Diagnostics is a string with stdout, stderr, and report excerpt for
    debugging verdict-parsing failures.

    ABICC exit codes:
      0 = compatible (no breaking changes)
      1 = incompatible (breaking changes found)
      other = error
    """
    # Write headers for ABICC descriptor
    old_desc = tmp_path / "old.xml"
    new_desc = tmp_path / "new.xml"

    h1_path = None
    if hdr_v1 is not None:
        h1_path = tmp_path / "old_hdr.h"
        h1_path.write_text(textwrap.dedent(hdr_v1).strip(), encoding="utf-8")

    h2_path = None
    if hdr_v2 is not None:
        h2_path = tmp_path / "new_hdr.h"
        h2_path.write_text(textwrap.dedent(hdr_v2).strip(), encoding="utf-8")

    _write_abicc_descriptor("1.0", old, h1_path, old_desc)
    _write_abicc_descriptor("2.0", new, h2_path, new_desc)

    report_path = tmp_path / "abicc_report.html"

    cmd = [
        "abi-compliance-checker",
        "-lib", "libtest",
        "-old", str(old_desc),
        "-new", str(new_desc),
        "-report-path", str(report_path),
    ]

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "subprocess timed out after 60s"

    # Build diagnostics string for debugging verdict-parsing failures.
    report_text = ""
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8", errors="replace")
    diag_parts = [
        f"rc={r.returncode}",
        f"stdout={r.stdout[:1000]!r}",
        f"stderr={r.stderr[:1000]!r}",
        f"report_exists={report_path.exists()}",
        f"report_len={len(report_text)}",
        f"report_first_2000={report_text[:2000]!r}",
    ]
    diag = "\n".join(diag_parts)

    if r.returncode == 1:
        return "BREAKING", diag

    if r.returncode != 0:
        return f"ERROR(rc={r.returncode})", diag

    # ABICC returns 0 for both no-change and compatible-additions.
    # Parse the structured HTML comment ABICC embeds at the top of reports:
    #   <!-- kind:binary;verdict:compatible;affected:0;added:0;removed:0;
    #        type_problems_high:0;...;tool_version:2.3 -->
    # If any change-count field is non-zero, it's COMPATIBLE.
    change_fields = (
        "affected", "added", "removed",
        "type_problems_high", "type_problems_medium", "type_problems_low",
        "interface_problems_high", "interface_problems_medium",
        "interface_problems_low", "changed_constants",
    )
    for field in change_fields:
        m = re.search(rf"{field}:(\d+)", report_text)
        if m and int(m.group(1)) > 0:
            return "COMPATIBLE", diag

    return "NO_CHANGE", diag


def _setup(
    name: str, src_v1: str, src_v2: str,
    hdr_v1: str | None, hdr_v2: str | None,
    lang: str, tmp_path: Path,
) -> tuple[str, str, str]:
    """Compile .so files, run both tools.

    Returns (abicheck_verdict, abicc_verdict, abicc_diagnostics).
    """
    _require_tool("abi-compliance-checker")
    _require_tool("gcc" if lang == "c" else "g++")
    if hdr_v1 is not None or hdr_v2 is not None:
        _require_tool("castxml")

    v1 = tmp_path / f"lib{name}_v1.so"
    v2 = tmp_path / f"lib{name}_v2.so"
    _compile_so(src_v1, v1, lang)
    _compile_so(src_v2, v2, lang)

    ac = _run_abicheck(v1, v2, hdr_v1, hdr_v2, lang, tmp_path)
    cc, diag = _run_abicc(v1, v2, hdr_v1, hdr_v2, tmp_path)
    return ac, cc, diag


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

@pytest.mark.abicc
@pytest.mark.parametrize(
    "name,src_v1,src_v2,hdr_v1,hdr_v2,lang,abicheck_exp,abicc_exp,_",
    _CONFIRMED, ids=[c[0] for c in _CONFIRMED],
)
def test_confirmed_parity(
    name: str, src_v1: str, src_v2: str,
    hdr_v1: str | None, hdr_v2: str | None, lang: str,
    abicheck_exp: str, abicc_exp: str, _: str, tmp_path: Path,
) -> None:
    """Both tools must agree on verdict -- full parity enforced."""
    ac, cc, diag = _setup(name, src_v1, src_v2, hdr_v1, hdr_v2, lang, tmp_path)
    assert ac == abicheck_exp, f"abicheck: expected {abicheck_exp}, got {ac}"
    assert cc == abicc_exp, f"abicc: expected {abicc_exp}, got {cc}\nDIAG:\n{diag}"
    assert ac == cc, f"PARITY BROKEN: abicheck={ac}, abicc={cc}"


@pytest.mark.abicc
@pytest.mark.parametrize(
    "name,src_v1,src_v2,hdr_v1,hdr_v2,lang,abicheck_exp,abicc_exp,_",
    _CORRECT, ids=[c[0] for c in _CORRECT],
)
def test_abicheck_correct(
    name: str, src_v1: str, src_v2: str,
    hdr_v1: str | None, hdr_v2: str | None, lang: str,
    abicheck_exp: str, abicc_exp: str, _: str, tmp_path: Path,
) -> None:
    """abicheck detects the break; ABICC misses it.

    If ABICC also becomes correct, move this case to _CONFIRMED.
    """
    ac, cc, diag = _setup(name, src_v1, src_v2, hdr_v1, hdr_v2, lang, tmp_path)
    assert ac == abicheck_exp, f"abicheck: expected {abicheck_exp}, got {ac}"
    assert cc == abicc_exp, f"abicc: expected {abicc_exp}, got {cc}\nDIAG:\n{diag}"
    if ac == cc:
        pytest.fail(
            f"Full parity achieved on '{name}' (both={ac}). "
            "Move this case to _CONFIRMED."
        )


@pytest.mark.abicc
@pytest.mark.parametrize(
    "name,src_v1,src_v2,hdr_v1,hdr_v2,lang,abicheck_exp,abicc_exp,_",
    _DIVERGE, ids=[c[0] for c in _DIVERGE],
)
def test_known_divergence(
    name: str, src_v1: str, src_v2: str,
    hdr_v1: str | None, hdr_v2: str | None, lang: str,
    abicheck_exp: str, abicc_exp: str, _: str, tmp_path: Path,
) -> None:
    """Intentional stable divergences. Fails if pattern changes unexpectedly."""
    ac, cc, diag = _setup(name, src_v1, src_v2, hdr_v1, hdr_v2, lang, tmp_path)

    if ac == cc == abicc_exp:
        pytest.fail(
            f"Gap closed on '{name}': abicheck now agrees with ABICC ({ac}). "
            "Move this case to _CONFIRMED and remove the divergence flag."
        )

    assert ac == abicheck_exp, (
        f"abicheck changed unexpectedly on '{name}': "
        f"expected {abicheck_exp}, got {ac}"
    )
    assert cc == abicc_exp, (
        f"ABICC changed unexpectedly on '{name}': "
        f"expected {abicc_exp}, got {cc}\nDIAG:\n{diag}"
    )
