"""Sprint 6: libabigail parity tests.

Verifies that abicheck and abidiff agree on ABI verdict for canonical
C/C++ library change scenarios. Tests are compiled locally (requires gcc/g++)
and compared with both tools.

Two test classes:
- test_confirmed_parity: both tools must agree (passing cases)
- test_known_divergence: documents current gaps, passes while gap is stable

Known divergences (documented, not failures):
- Type-change cases (struct_size, return_type, param_type, vtable_reorder):
  abicheck ELF-only mode cannot detect type changes without headers/DWARF;
  abidiff reads DWARF debug info compiled into the .so with -g.
- enum_value: abicheck is MORE conservative (BREAKING), abidiff says COMPATIBLE.
  Our behavior is intentional — enum value changes break switch/serialization.

G3 roadmap: close DWARF gaps in Sprint 7 by passing headers to dump().

Requires: abidiff (libabigail-tools), gcc/g++.
"""
from __future__ import annotations

import shutil
import subprocess
import textwrap
import warnings
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Cases: (name, src_v1, src_v2, lang, abicheck_expected, abidiff_expected, is_divergence)
# ---------------------------------------------------------------------------
PARITY_CASES: list[tuple[str, str, str, str, str, str, bool]] = [
    (
        "fn_removed",
        "int add(int a, int b) { return a + b; }\nint sub(int a, int b) { return a - b; }",
        "int add(int a, int b) { return a + b; }",
        "c", "BREAKING", "BREAKING", False,
    ),
    (
        "fn_added",
        "int add(int a, int b) { return a + b; }",
        "int add(int a, int b) { return a + b; }\nint mul(int a, int b) { return a*b; }",
        "c", "COMPATIBLE", "COMPATIBLE", False,
    ),
    (
        "no_change",
        "int add(int a, int b) { return a + b; }",
        "int add(int a, int b) { return a + b; }",
        "c", "NO_CHANGE", "NO_CHANGE", False,
    ),
    (
        "visibility_hidden",
        '__attribute__((visibility("default"))) int helper() { return 1; }\n'
        '__attribute__((visibility("default"))) int api()    { return helper(); }',
        '__attribute__((visibility("hidden")))  int helper() { return 1; }\n'
        '__attribute__((visibility("default"))) int api()    { return helper(); }',
        "c", "BREAKING", "BREAKING", False,
    ),
    # ── Known gaps: ELF-only cannot detect type-level changes ─────────────
    # abicheck with castxml detects struct size → BREAKING.
    # abidiff without --headers-dir: sub-type change → COMPATIBLE (exit=4).
    # abicheck is stricter — intentional divergence.
    (
        "struct_size",
        "typedef struct { int x; } Point;\n"
        "Point make_point(int x) { Point p = {x}; return p; }",
        "typedef struct { int x; int y; } Point;\n"
        "Point make_point(int x) { Point p = {x, 0}; return p; }",
        "c", "BREAKING", "COMPATIBLE", True,
    ),
    # abicheck ELF-only: same symbol name, no type info → NO_CHANGE.
    # abidiff DWARF: sees sub-type drift → COMPATIBLE (exit=4, not BREAKING).
    (
        "return_type",
        "int  get_val(void) { return 42; }",
        "long get_val(void) { return 42; }",
        "c", "NO_CHANGE", "COMPATIBLE", True,
    ),
    (
        "param_type",
        "void set_val(int x); void set_val(int x) {}",
        "void set_val(long x); void set_val(long x) {}",
        "c", "NO_CHANGE", "COMPATIBLE", True,
    ),
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
        "cpp", "NO_CHANGE", "BREAKING", True,
    ),
    # ── Intentional divergence: abicheck is more conservative ────────────
    (
        "enum_value",
        "typedef enum { RED=0, GREEN=1, BLUE=2 } Color;\n"
        "Color get_color(void) { return RED; }",
        "typedef enum { RED=0, GREEN=10, BLUE=2 } Color;\n"
        "Color get_color(void) { return RED; }",
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


def _run_abicheck(old: Path, new: Path) -> str:
    try:
        from abicheck.checker import compare
        from abicheck.dumper import dump
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            old_snap = dump(old, headers=[], version="v1")
            new_snap = dump(new, headers=[], version="v2")
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
    Bit 3 takes priority when both bits 2 and 3 are set.
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
_CONFIRMED = [c for c in PARITY_CASES if not c[6]]
_DIVERGE = [c for c in PARITY_CASES if c[6]]


@pytest.mark.libabigail
@pytest.mark.parametrize(
    "name,src_v1,src_v2,lang,abicheck_exp,abidiff_exp,_",
    _CONFIRMED, ids=[c[0] for c in _CONFIRMED],
)
def test_confirmed_parity(
    name: str, src_v1: str, src_v2: str, lang: str,
    abicheck_exp: str, abidiff_exp: str, _: bool, tmp_path: Path,
) -> None:
    """Both tools must agree on verdict — no acceptable divergence."""
    _require_tool("abidiff")
    _require_tool("gcc" if lang == "c" else "g++")

    v1 = tmp_path / f"lib{name}_v1.so"
    v2 = tmp_path / f"lib{name}_v2.so"
    _compile_so(src_v1, v1, lang)
    _compile_so(src_v2, v2, lang)

    ac = _run_abicheck(v1, v2)
    ab = _run_abidiff(v1, v2)

    assert ac == abicheck_exp, f"abicheck: expected {abicheck_exp}, got {ac}"
    assert ab == abidiff_exp, f"abidiff: expected {abidiff_exp}, got {ab}"
    assert ac == ab, f"PARITY BROKEN: abicheck={ac}, abidiff={ab}"


@pytest.mark.libabigail
@pytest.mark.parametrize(
    "name,src_v1,src_v2,lang,abicheck_exp,abidiff_exp,_",
    _DIVERGE, ids=[c[0] for c in _DIVERGE],
)
def test_known_divergence(
    name: str, src_v1: str, src_v2: str, lang: str,
    abicheck_exp: str, abidiff_exp: str, _: bool, tmp_path: Path,
) -> None:
    """Document current gaps. Fails when divergence pattern unexpectedly changes.

    When a gap is closed (abicheck catches up to abidiff), update the
    expected values in PARITY_CASES and move the case to _CONFIRMED.
    """
    _require_tool("abidiff")
    _require_tool("gcc" if lang == "c" else "g++")

    v1 = tmp_path / f"lib{name}_v1.so"
    v2 = tmp_path / f"lib{name}_v2.so"
    _compile_so(src_v1, v1, lang)
    _compile_so(src_v2, v2, lang)

    ac = _run_abicheck(v1, v2)
    ab = _run_abidiff(v1, v2)

    if ac == ab == abidiff_exp:
        # Gap closed correctly: abicheck caught up to the authoritative abidiff verdict.
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
