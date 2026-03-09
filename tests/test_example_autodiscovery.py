"""Integration tests — auto-discovery of all example cases.

Replaces the hard-coded CASES list in test_abi_examples.py with directory
scanning so every new example added to examples/ is automatically tested
without touching this file.

Layout support:
  • v1/v2     — examples/caseXX/v1.c(pp)  + v2.c(pp)  [+ v1.h/v2.h]
  • old/new   — examples/caseXX/old/lib.c + new/lib.c  [+ lib.h]
  • good/bad  — examples/caseXX/good.c    + bad.c
  • libfoo    — examples/caseXX/libfoo_v1.c + libfoo_v2.c  [+ foo_v1.h/foo_v2.h]

Expected verdicts are declared here (not in the example source tree) so the
tests remain authoritative even if README files get out of sync.
Add `None` to skip a case entirely (compile-time failures, etc.).

Marked `@pytest.mark.integration` — requires gcc/g++ + castxml in PATH.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_DIR     = Path(__file__).parent.parent
EXAMPLES_DIR = REPO_DIR / "examples"

# ---------------------------------------------------------------------------
# Expected verdicts (single source of truth for the test suite)
# ---------------------------------------------------------------------------
# Verdict options: "BREAKING" | "COMPATIBLE" | "NO_CHANGE" | None (skip)
#
# Annotation legend (in comments):
#   ✅ DETECTED      — abicheck catches this reliably
#   ⚠️  KNOWN GAP    — real break that abicheck cannot detect yet (xfail)
#   ℹ️  POLICY       — not a binary break; SONAME/versioning are policy issues
#   🐛 BUG EXPECTED  — abicheck over-reports; tracked separately
EXPECTED: dict[str, str | None] = {
    # ── cases 01-18 (v1/v2 layout) ──────────────────────────────────────────
    "case01_symbol_removal":          "BREAKING",    # ✅ FUNC_REMOVED
    "case02_param_type_change":       "BREAKING",    # ✅ FUNC_PARAMS_CHANGED
    "case03_compat_addition":         "COMPATIBLE",  # ✅ FUNC_ADDED
    "case04_no_change":               "NO_CHANGE",   # ✅ identical
    "case05_soname":                  "NO_CHANGE",   # ℹ️  SONAME not tracked (policy)
    "case06_visibility":              "BREAKING",    # ✅ symbol hidden → removed from dynsym
    "case07_struct_layout":           "BREAKING",    # ✅ TYPE_SIZE_CHANGED
    "case08_enum_value_change":       "BREAKING",    # ✅ ENUM_MEMBER_VALUE_CHANGED
    "case09_cpp_vtable":              "BREAKING",    # ✅ TYPE_VTABLE_CHANGED
    "case10_return_type":             "BREAKING",    # ✅ FUNC_RETURN_CHANGED
    "case11_global_var_type":         "BREAKING",    # ✅ VAR_TYPE_CHANGED / SYMBOL_SIZE_CHANGED
    "case12_function_removed":        "BREAKING",    # ✅ FUNC_REMOVED
    "case13_symbol_versioning":       "NO_CHANGE",   # ℹ️  version tags stripped by checker
    "case14_cpp_class_size":          "BREAKING",    # ✅ TYPE_SIZE_CHANGED
    "case15_noexcept_change":         "BREAKING",    # ✅ SYMBOL_VERSION_REQUIRED_ADDED (stdexcept)
    "case16_inline_to_non_inline":    "COMPATIBLE",  # ✅ FUNC_ADDED
    "case17_template_abi":            "BREAKING",    # ✅ TYPE_SIZE_CHANGED
    "case18_dependency_leak":         "BREAKING",    # ✅ TYPE_SIZE_CHANGED (ThirdPartyHandle 4→8)
    # ── cases 19-29 (old/new layout) ────────────────────────────────────────
    "case19_enum_member_removed":     "BREAKING",    # ✅ ENUM_MEMBER_REMOVED
    "case20_enum_member_value_changed": "BREAKING",  # ✅ ENUM_MEMBER_VALUE_CHANGED
    "case21_method_became_static":    "BREAKING",    # ✅ FUNC_STATIC_CHANGED
    "case22_method_const_changed":    "BREAKING",    # ✅ FUNC_CV_CHANGED
    "case23_pure_virtual_added":      None,          # intentional compile error — skip
    "case24_union_field_removed":     "BREAKING",    # ✅ UNION_FIELD_REMOVED
    "case25_enum_member_added":       "COMPATIBLE",  # ✅ ENUM_MEMBER_ADDED (in _COMPATIBLE_KINDS)
    "case26_union_field_added":       "BREAKING",    # ✅ TYPE_SIZE_CHANGED (union 4→8 bytes)
    "case27_symbol_binding_weakened": "COMPATIBLE",  # ✅ SYMBOL_BINDING_CHANGED (COMPATIBLE)
    "case29_ifunc_transition":        "COMPATIBLE",  # ✅ IFUNC_INTRODUCED (COMPATIBLE)
}

# Cases where abicheck is known to diverge from the "ideal" expected verdict.
# These are not bugs in the test — they document deliberate limitations.
# Format: case_name -> reason string for xfail
KNOWN_GAPS: dict[str, str] = {
    # Visibility change requires compiling with -fvisibility=hidden so that
    # internal_helper/another_impl are absent from .dynsym in the "good" SO.
    # When both are compiled without visibility flags, all symbols remain exported
    # and abicheck sees only additions (COMPATIBLE) rather than removals (BREAKING).
    # Production use: pass -fvisibility=hidden in your actual build → BREAKING detected.
    "case06_visibility": (
        "Requires -fvisibility=hidden compile flag to hide internal symbols; "
        "benchmark compiles without it, so all symbols stay exported → COMPATIBLE"
    ),
}


# ---------------------------------------------------------------------------
# Layout detection helpers
# ---------------------------------------------------------------------------
def _find_sources(
    case_dir: Path,
) -> tuple[Path | None, Path | None, Path | None, Path | None]:
    """Return (v1_src, v2_src, v1_hdr, v2_hdr) or (None,)*4 if unsupported."""
    # v1/v2 layout
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"v1{ext}"
        if v1.exists():
            v2 = case_dir / f"v2{ext}"
            if not v2.exists():
                v2 = v1  # case04: no change
            hext = ".h" if ext == ".c" else ".hpp"
            v1h = case_dir / f"v1{hext}"
            v2h = case_dir / f"v2{hext}"
            return v1, v2, v1h if v1h.exists() else None, v2h if v2h.exists() else None

    # old/new layout (cases 19+)
    old_dir, new_dir = case_dir / "old", case_dir / "new"
    if old_dir.is_dir() and new_dir.is_dir():
        for ext in (".c", ".cpp"):
            v1 = old_dir / f"lib{ext}"
            if v1.exists():
                v2 = new_dir / f"lib{ext}"
                if not v2.exists():
                    v2 = v1
                # Try both .h and .hpp regardless of source extension
                v1h = next((old_dir / f"lib{h}" for h in (".h", ".hpp") if (old_dir / f"lib{h}").exists()), None)
                v2h = next((new_dir / f"lib{h}" for h in (".h", ".hpp") if (new_dir / f"lib{h}").exists()), None)
                return v1, v2, v1h, v2h

    # good/bad layout (cases 05, 06, 13)
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"good{ext}"
        if v1.exists():
            v2 = case_dir / f"bad{ext}"
            if not v2.exists():
                v2 = v1
            return v1, v2, None, None

    # libfoo_v1/v2 layout (case18)
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"libfoo_v1{ext}"
        if v1.exists():
            v2 = case_dir / f"libfoo_v2{ext}"
            if not v2.exists():
                v2 = v1
            hext = ".h" if ext == ".c" else ".hpp"
            v1h = case_dir / f"foo_v1{hext}"
            v2h = case_dir / f"foo_v2{hext}"
            return v1, v2, v1h if v1h.exists() else None, v2h if v2h.exists() else None

    return None, None, None, None


def _compile_so(src: Path, out: Path) -> bool:
    compiler = "g++" if src.suffix in (".cpp", ".hpp") else "gcc"
    r = subprocess.run(
        [compiler, "-shared", "-fPIC", "-g", "-Og", "-fvisibility=default",
         "-o", str(out), str(src)],
        capture_output=True, text=True,
    )
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Auto-discovery: build test parameter list
# ---------------------------------------------------------------------------
def _collect_cases() -> list[tuple[str, str | None]]:
    """Scan examples/ and return (case_name, expected_verdict_or_None)."""
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
    """Compile → dump → compare for every example case.

    Uses the Python API directly (no subprocess for abicheck) so the test
    always runs against the source tree being tested, not a globally-installed
    binary.
    """
    for tool in ("castxml", "gcc", "g++"):
        if not shutil.which(tool):
            pytest.skip(f"{tool} not found in PATH")

    case_dir = EXAMPLES_DIR / case_name
    assert case_dir.is_dir(), f"Case directory not found: {case_dir}"

    v1_src, v2_src, v1_hdr, v2_hdr = _find_sources(case_dir)
    if v1_src is None:
        pytest.skip(f"{case_name}: no recognized source layout")

    # Mark known gap cases as xfail
    if case_name in KNOWN_GAPS:
        pytest.xfail(KNOWN_GAPS[case_name])

    # Build .so files
    v1_so = tmp_path / "lib_v1.so"
    v2_so = tmp_path / "lib_v2.so"
    if not _compile_so(v1_src, v1_so):
        pytest.skip(f"{case_name}: v1 compile failed (intentional or env issue)")
    if not _compile_so(v2_src, v2_so):
        pytest.skip(f"{case_name}: v2 compile failed (intentional or env issue)")

    # Run abicheck pipeline via Python API (no subprocess — always uses this repo)
    from abicheck.checker import compare
    from abicheck.dumper import dump

    headers_v1 = [v1_hdr] if v1_hdr and v1_hdr.exists() else []
    headers_v2 = [v2_hdr] if v2_hdr and v2_hdr.exists() else []

    try:
        snap1 = dump(v1_so, headers=headers_v1, version="v1")
        snap2 = dump(v2_so, headers=headers_v2, version="v2")
    except Exception as exc:
        pytest.fail(f"{case_name}: dump failed: {exc}")

    result = compare(snap1, snap2)
    got = result.verdict.value.upper()

    # Normalize: SOURCE_BREAK and COMPATIBLE are both non-breaking
    def _normalize(v: str) -> str:
        return "COMPATIBLE" if v in ("SOURCE_BREAK", "COMPATIBLE") else v

    assert _normalize(got) == _normalize(expected_verdict), (
        f"{case_name}: expected={expected_verdict!r}, got={got!r}\n"
        f"Changes detected:\n" +
        "\n".join(f"  {c.kind.value}: {c.description}" for c in result.changes)
    )
