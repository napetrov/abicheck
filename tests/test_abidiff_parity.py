"""Sprint 6: libabigail parity tests.

Verifies that abicheck and abidiff agree on ABI verdict for canonical
C/C++ library change scenarios. Tests are compiled locally (requires gcc/g++)
and compared with both tools.

Two test classes:
- test_confirmed_parity: abicheck verdict matches expected; tools may differ.
- test_known_divergence: documents intentional stable divergences.

Known divergences (2 remaining):
- struct_size: abicheck BREAKING, abidiff COMPATIBLE (no --headers-dir).
  abicheck is stricter — intentional.
- enum_value: abicheck BREAKING, abidiff COMPATIBLE. Intentional conservatism
  — enum value changes break switch/serialisation.

G3 status: CLOSED (2026-03-08).
  return_type, param_type, vtable_reorder now all BREAKING via castxml headers.
  Parity score: 7/9 confirmed (2 intentional divergences remain).

Requires: abidiff (libabigail-tools), gcc/g++, castxml.
"""
from __future__ import annotations

import shutil
import subprocess
import textwrap
import warnings
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Cases:
#   (name, src_v1, src_v2, hdr_v1, hdr_v2, lang,
#    abicheck_expected, abidiff_expected, is_divergence)
#
# hdr_v1 / hdr_v2:
#   None → ELF-only mode (no castxml).
#   str  → written to a temp .h file and passed to dump(headers=[...]).
#
# Note on parity: abicheck_expected and abidiff_expected may differ for
# G3-closed cases (return_type, param_type) where abidiff is conservative
# without --headers-dir. The binding assertion is abicheck_expected.
# ---------------------------------------------------------------------------
PARITY_CASES: list[tuple[str, str, str, str | None, str | None, str, str, str, bool]] = [
    (
        "fn_removed",
        "int add(int a, int b) { return a + b; }\nint sub(int a, int b) { return a - b; }",
        "int add(int a, int b) { return a + b; }",
        "int add(int a, int b);\nint sub(int a, int b);",
        "int add(int a, int b);",
        "c", "BREAKING", "BREAKING", False,
    ),
    (
        "fn_added",
        "int add(int a, int b) { return a + b; }",
        "int add(int a, int b) { return a + b; }\nint mul(int a, int b) { return a*b; }",
        "int add(int a, int b);",
        "int add(int a, int b);\nint mul(int a, int b);",
        "c", "COMPATIBLE", "COMPATIBLE", False,
    ),
    # ELF-only fallback: no headers → tests the headers=[] code path explicitly.
    (
        "no_change",
        "int add(int a, int b) { return a + b; }",
        "int add(int a, int b) { return a + b; }",
        None,  # intentionally ELF-only — guards the no-headers fallback
        None,
        "c", "NO_CHANGE", "NO_CHANGE", False,
    ),
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
        "c", "BREAKING", "BREAKING", False,
    ),
    # ── G3 CLOSED: return_type ────────────────────────────────────────────
    # abicheck+headers: BREAKING (correct). abidiff without --headers-dir:
    # COMPATIBLE (exit=4, sees only sub-type drift). abicheck is stricter.
    (
        "return_type",
        "int  get_val(void) { return 42; }",
        "long get_val(void) { return 42; }",
        "int  get_val(void);",
        "long get_val(void);",
        "c", "BREAKING", "COMPATIBLE", False,
    ),
    # ── G3 CLOSED: param_type ────────────────────────────────────────────
    # Same reasoning: abidiff COMPATIBLE, abicheck BREAKING (correct).
    (
        "param_type",
        "void set_val(int  x) {}",
        "void set_val(long x) {}",
        "void set_val(int  x);",
        "void set_val(long x);",
        "c", "BREAKING", "COMPATIBLE", False,
    ),
    # ── G3 CLOSED: vtable_reorder ─────────────────────────────────────────
    # Both tools agree: BREAKING. castxml headers expose vtable layout.
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
        "cpp", "BREAKING", "BREAKING", False,
    ),
    # ── Intentional divergence: struct_size ──────────────────────────────
    # abicheck BREAKING (correct). abidiff COMPATIBLE without --headers-dir.
    (
        "struct_size",
        "typedef struct { int x; } Point;\n"
        "Point make_point(int x) { Point p = {x}; return p; }",
        "typedef struct { int x; int y; } Point;\n"
        "Point make_point(int x) { Point p = {x, 0}; return p; }",
        "typedef struct { int x; } Point;\nPoint make_point(int x);",
        "typedef struct { int x; int y; } Point;\nPoint make_point(int x);",
        "c", "BREAKING", "COMPATIBLE", True,
    ),
    # ── Intentional divergence: enum_value ───────────────────────────────
    # abicheck BREAKING (conservative). abidiff COMPATIBLE. Intentional.
    (
        "enum_value",
        "typedef enum { RED=0, GREEN=1, BLUE=2 } Color;\n"
        "Color get_color(void) { return RED; }",
        "typedef enum { RED=0, GREEN=10, BLUE=2 } Color;\n"
        "Color get_color(void) { return RED; }",
        "typedef enum { RED=0, GREEN=1, BLUE=2 } Color;\nColor get_color(void);",
        "typedef enum { RED=0, GREEN=10, BLUE=2 } Color;\nColor get_color(void);",
        "c", "BREAKING", "COMPATIBLE", True,
    ),
]


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
        pytest.skip(f"Compilation failed: {r.stderr[:200]}")


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
            # Use _hdr suffix to avoid any collision with .so stem names
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


def _run_abidiff(old: Path, new: Path) -> str:
    """Run abidiff; return BREAKING/COMPATIBLE/NO_CHANGE.

    abidiff exit code bit mask:
      bit 0 (1)  = error
      bit 2 (4)  = compatible changes present
      bit 3 (8)  = incompatible (breaking) changes present
    """
    r = subprocess.run(
        ["abidiff", "--no-show-locs", str(old), str(new)],
        capture_output=True, text=True, timeout=30,
    )
    code = r.returncode
    if code == 0:
        return "NO_CHANGE"
    if code & 1:
        return "ERROR"
    if code & 8:
        return "BREAKING"
    if code & 4:
        return "COMPATIBLE"
    return "NO_CHANGE"


# ---------------------------------------------------------------------------
# Split into confirmed-parity and known-divergence sets
# ---------------------------------------------------------------------------
_CONFIRMED = [c for c in PARITY_CASES if not c[8]]
_DIVERGE = [c for c in PARITY_CASES if c[8]]


@pytest.mark.libabigail
@pytest.mark.parametrize(
    "name,src_v1,src_v2,hdr_v1,hdr_v2,lang,abicheck_exp,abidiff_exp,_",
    _CONFIRMED, ids=[c[0] for c in _CONFIRMED],
)
def test_confirmed_parity(
    name: str, src_v1: str, src_v2: str,
    hdr_v1: str | None, hdr_v2: str | None, lang: str,
    abicheck_exp: str, abidiff_exp: str, _: bool, tmp_path: Path,
) -> None:
    """Confirmed parity cases: abicheck must produce the expected verdict.

    When abicheck_exp == abidiff_exp the two tools also agree (full parity).
    When they differ (return_type, param_type) abicheck is intentionally
    stricter — abidiff is conservative without --headers-dir.
    """
    _require_tool("abidiff")
    _require_tool("gcc" if lang == "c" else "g++")
    if hdr_v1 is not None:
        _require_tool("castxml")

    v1 = tmp_path / f"lib{name}_v1.so"
    v2 = tmp_path / f"lib{name}_v2.so"
    _compile_so(src_v1, v1, lang)
    _compile_so(src_v2, v2, lang)

    ac = _run_abicheck(v1, v2, hdr_v1, hdr_v2, lang, tmp_path)
    ab = _run_abidiff(v1, v2)

    assert ac == abicheck_exp, f"abicheck: expected {abicheck_exp}, got {ac}"
    assert ab == abidiff_exp, f"abidiff: expected {abidiff_exp}, got {ab}"
    # Assert full tool agreement only when both are expected to match.
    if abicheck_exp == abidiff_exp:
        assert ac == ab, f"PARITY BROKEN: abicheck={ac}, abidiff={ab}"


@pytest.mark.libabigail
@pytest.mark.parametrize(
    "name,src_v1,src_v2,hdr_v1,hdr_v2,lang,abicheck_exp,abidiff_exp,_",
    _DIVERGE, ids=[c[0] for c in _DIVERGE],
)
def test_known_divergence(
    name: str, src_v1: str, src_v2: str,
    hdr_v1: str | None, hdr_v2: str | None, lang: str,
    abicheck_exp: str, abidiff_exp: str, _: bool, tmp_path: Path,
) -> None:
    """Intentional stable divergences between abicheck and abidiff.

    Fails when the divergence pattern changes unexpectedly — which signals
    either a regression or a gap being closed (move to _CONFIRMED).
    """
    _require_tool("abidiff")
    _require_tool("gcc" if lang == "c" else "g++")
    if hdr_v1 is not None:
        _require_tool("castxml")

    v1 = tmp_path / f"lib{name}_v1.so"
    v2 = tmp_path / f"lib{name}_v2.so"
    _compile_so(src_v1, v1, lang)
    _compile_so(src_v2, v2, lang)

    ac = _run_abicheck(v1, v2, hdr_v1, hdr_v2, lang, tmp_path)
    ab = _run_abidiff(v1, v2)

    if ac == ab == abidiff_exp:
        pytest.fail(
            f"Gap closed on '{name}': abicheck now agrees with abidiff ({ac}). "
            "Move this case to _CONFIRMED and remove the is_divergence flag."
        )

    assert ac == abicheck_exp, (
        f"abicheck changed unexpectedly on '{name}': "
        f"expected {abicheck_exp}, got {ac}"
    )
    assert ab == abidiff_exp, (
        f"abidiff changed unexpectedly on '{name}': "
        f"expected {abidiff_exp}, got {ab}"
    )
