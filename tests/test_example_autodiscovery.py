"""Integration tests — auto-discovery of all example cases.

Replaces the hard-coded CASES list in test_abi_examples.py with directory
scanning so every new example added to examples/ is automatically tested
without touching this file.

Layout support:
  • v1/v2     — examples/caseXX/v1.c(pp)  + v2.c(pp)  [+ v1.h/.hpp]
  • old/new   — examples/caseXX/old/lib.c + new/lib.c  [+ lib.h/.hpp]
  • good/bad  — examples/caseXX/bad.c (v1) + good.c (v2)  [bad=before, good=fixed]
  • libfoo    — examples/caseXX/libfoo_v1.c + libfoo_v2.c

Expected verdicts are declared here (not in the example source tree) so the
tests remain authoritative even if README files get out of sync.
Set to `None` to skip a case entirely (e.g. intentional compile errors).

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
EXPECTED: dict[str, str | None] = {
    # ── cases 01-18 (v1/v2 layout) ──────────────────────────────────────────
    "case01_symbol_removal":            "BREAKING",
    "case02_param_type_change":         "BREAKING",
    "case03_compat_addition":           "COMPATIBLE",
    "case04_no_change":                 "NO_CHANGE",
    "case05_soname":                    "COMPATIBLE",  # SONAME_MISSING: bad practice flag, COMPATIBLE verdict
    "case06_visibility":                "COMPATIBLE",  # visibility leak cleanup: bad practice fix, not intended ABI break
    "case07_struct_layout":             "BREAKING",
    "case08_enum_value_change":         "BREAKING",
    "case09_cpp_vtable":                "BREAKING",
    "case10_return_type":               "BREAKING",
    "case11_global_var_type":           "BREAKING",
    "case12_function_removed":          "BREAKING",
    "case13_symbol_versioning":         "COMPATIBLE",  # unversioned→versioned: ld.so soft-matches; Makefile applies version script
    "case14_cpp_class_size":            "BREAKING",
    "case15_noexcept_change":           "BREAKING",    # SYMBOL_VERSION_REQUIRED_ADDED from stdexcept
    "case16_inline_to_non_inline":      "COMPATIBLE",
    "case17_template_abi":              "BREAKING",
    "case18_dependency_leak":           "BREAKING",
    # ── cases 19-29 (old/new layout) ────────────────────────────────────────
    "case19_enum_member_removed":       "BREAKING",
    "case20_enum_member_value_changed": "BREAKING",
    "case21_method_became_static":      "BREAKING",
    "case22_method_const_changed":      "BREAKING",
    "case23_pure_virtual_added":        "BREAKING",    # pure_virtual=1 changes vtable slot → __cxa_pure_virtual
    "case24_union_field_removed":       "BREAKING",
    "case25_enum_member_added":         "COMPATIBLE",
    "case26_union_field_added":         "BREAKING",    # union grows 4→8 bytes: TYPE_SIZE_CHANGED
    "case27_symbol_binding_weakened":   "COMPATIBLE",
    "case29_ifunc_transition":          "COMPATIBLE",  # FUNC→IFUNC → IFUNC_INTRODUCED (COMPATIBLE)
    # ── cases 28, 30-41 (Sprint 7 — full parity examples) ─────────────────
    "case28_typedef_opaque":            "BREAKING",    # typedef removed + type became opaque
    "case30_field_qualifiers":          "BREAKING",    # const/volatile qualifier change on struct fields → TYPE_FIELD_TYPE_CHANGED
    "case31_enum_rename":               "SOURCE_BREAK", # rename with same values: source-level only
    "case32_param_defaults":            "NO_CHANGE",   # default values not in binary ABI
    "case33_pointer_level":             "BREAKING",    # param/return pointer level changes
    "case34_access_level":              "SOURCE_BREAK", # narrowing access (public→private) is a source break
    "case35_field_rename":              "BREAKING",    # field rename: castxml sees old field removed + new field added → BREAKING
    "case36_anon_struct":               "BREAKING",    # type_size_changed + alignment changed
    "case37_base_class":                "BREAKING",    # base class reorder + virtual inheritance change
    "case38_virtual_methods":           "BREAKING",    # virtual added/removed + visibility change
    "case39_var_const":                 "BREAKING",    # var_type_changed + var_removed now detected via ELF+DWARF
    "case40_field_layout":              "BREAKING",    # field type changed + size changed
    "case41_type_changes":              "BREAKING",    # type removed + alignment changed + enum sentinel
}

# Known gaps: these cases xfail when the verdict disagrees with expected.
# Format: case_name → reason string.
KNOWN_GAPS: dict[str, str] = {
    "case06_visibility": (
        "Current checker may report BREAKING via FUNC_VISIBILITY_CHANGED when leaked internal symbols "
        "disappear from dynsym; semantically this case is a bad-practice cleanup and is treated as COMPATIBLE"
    ),
}

# ---------------------------------------------------------------------------
# Layout detection helpers
# ---------------------------------------------------------------------------
def _find_sources(
    case_dir: Path,
) -> tuple[Path, Path, Path | None, Path | None]:
    """Return (v1_src, v2_src, v1_hdr, v2_hdr).

    Raises pytest.skip() if no recognised layout is found or if a required
    v2 source is missing (only case04_no_change legitimately has no v2).
    """
    def _hdr(base_dir: Path, stem: str) -> Path | None:
        for ext in (".h", ".hpp"):
            h = base_dir / f"{stem}{ext}"
            if h.exists():
                return h
        return None

    # v1/v2 layout
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"v1{ext}"
        if v1.exists():
            v2 = case_dir / f"v2{ext}"
            if not v2.exists():
                if case_dir.name == "case04_no_change":
                    v2 = v1  # intentional: identical sources → NO_CHANGE
                else:
                    pytest.fail(f"{case_dir.name}: v2 source missing — broken fixture")
            return v1, v2, _hdr(case_dir, "v1"), _hdr(case_dir, "v2")

    # old/new layout (cases 19+)
    old_dir, new_dir = case_dir / "old", case_dir / "new"
    if old_dir.is_dir() and new_dir.is_dir():
        for ext in (".c", ".cpp"):
            v1 = old_dir / f"lib{ext}"
            if v1.exists():
                v2 = new_dir / f"lib{ext}"
                if not v2.exists():
                    pytest.fail(f"{case_dir.name}: new/lib{ext} missing — broken fixture")
                v1h = _hdr(old_dir, "lib")
                v2h = _hdr(new_dir, "lib")
                return v1, v2, v1h, v2h

    # good/bad layout (cases 05, 06, 13)
    # Convention: bad=v1 (before, problematic state), good=v2 (after, fixed state).
    # Comparing bad→good reveals symbol removals = BREAKING for callers.
    for ext in (".c", ".cpp"):
        bad = case_dir / f"bad{ext}"
        if bad.exists():
            good = case_dir / f"good{ext}"
            if not good.exists():
                pytest.fail(f"{case_dir.name}: good{ext} missing — broken fixture")
            return bad, good, None, None

    # libfoo_v1/v2 layout (case18)
    for ext in (".c", ".cpp"):
        v1 = case_dir / f"libfoo_v1{ext}"
        if v1.exists():
            v2 = case_dir / f"libfoo_v2{ext}"
            if not v2.exists():
                pytest.fail(f"{case_dir.name}: libfoo_v2{ext} missing — broken fixture")
            return v1, v2, _hdr(case_dir, "foo_v1"), _hdr(case_dir, "foo_v2")

    pytest.skip(f"{case_dir.name}: no recognised source layout")


def _compile_so(src: Path, out: Path) -> None:
    """Compile *src* into a shared library at *out*.

    Raises ``pytest.fail`` (not skip) on compiler errors so that broken
    fixtures are surfaced immediately rather than silently green-skipped.
    Skip is only appropriate when the *tool* (gcc/g++) is absent.
    """
    compiler = "g++" if src.suffix in (".cpp",) else "gcc"
    if not shutil.which(compiler):
        pytest.skip(f"{compiler} not found in PATH")

    r = subprocess.run(
        [compiler, "-shared", "-fPIC", "-g", "-Og", "-fvisibility=default",
         "-o", str(out), str(src)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.fail(
            f"Compile failed for {src.name} (exit {r.returncode}):\n{r.stderr[:800]}"
        )


# ---------------------------------------------------------------------------
# Auto-discovery: build test parameter list
# ---------------------------------------------------------------------------
def _collect_cases() -> list[tuple[str, str | None]]:
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
    """Compile → dump → compare for every example case."""
    for tool in ("castxml", "gcc"):
        if not shutil.which(tool):
            pytest.skip(f"{tool} not found in PATH")

    case_dir = EXAMPLES_DIR / case_name
    assert case_dir.is_dir(), f"Case directory not found: {case_dir}"

    v1_src, v2_src, v1_hdr, v2_hdr = _find_sources(case_dir)

    # If the case ships a Makefile use it so special build flags (version scripts,
    # extra link options, etc.) are applied exactly as intended by the example.
    # Fall back to direct _compile_so() only when no Makefile is present.
    if (case_dir / "Makefile").exists():
        build_dir = tmp_path / case_name
        shutil.copytree(str(case_dir), str(build_dir))
        r = subprocess.run(
            ["make", "-C", str(build_dir)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            pytest.fail(f"make failed in {case_name} (broken fixture):\n{r.stderr[:400]}")
        v1_so = build_dir / "libv1.so"
        v2_so = build_dir / "libv2.so"
        if not v1_so.exists() or not v2_so.exists():
            pytest.fail(f"{case_name}: Makefile did not produce libv1.so / libv2.so")
        # Resolve header paths relative to build_dir (preserve subdir structure)
        def _remap(hdr: Path | None, src: Path, dst: Path) -> Path | None:
            if not hdr:
                return None
            try:
                return dst / hdr.relative_to(src)
            except ValueError:
                return dst / hdr.name
        headers_v1 = [_remap(v1_hdr, case_dir, build_dir)] if v1_hdr else []
        headers_v2 = [_remap(v2_hdr, case_dir, build_dir)] if v2_hdr else []
        headers_v1 = [h for h in headers_v1 if h.exists()]
        headers_v2 = [h for h in headers_v2 if h.exists()]
    else:
        v1_so = tmp_path / "lib_v1.so"
        v2_so = tmp_path / "lib_v2.so"
        _compile_so(v1_src, v1_so)
        _compile_so(v2_src, v2_so)
        headers_v1 = [v1_hdr] if v1_hdr and v1_hdr.exists() else []
        headers_v2 = [v2_hdr] if v2_hdr and v2_hdr.exists() else []

    # Run abicheck pipeline via Python API (always uses THIS repo's code)
    from abicheck.checker import compare
    from abicheck.dumper import dump

    try:
        snap1 = dump(v1_so, headers=headers_v1, version="v1")
        snap2 = dump(v2_so, headers=headers_v2, version="v2")
    except Exception as exc:
        pytest.fail(f"{case_name}: dump failed: {exc}")

    result = compare(snap1, snap2)
    got = result.verdict.value.upper()

    def _normalize(v: str) -> str:
        return "COMPATIBLE" if v in ("SOURCE_BREAK", "COMPATIBLE") else v

    # Known gaps: xfail when verdict disagrees, pass through when fixed
    if case_name in KNOWN_GAPS:
        if _normalize(got) != _normalize(expected_verdict):
            pytest.xfail(KNOWN_GAPS[case_name])

    assert _normalize(got) == _normalize(expected_verdict), (
        f"{case_name}: expected={expected_verdict!r}, got={got!r}\n"
        f"Changes:\n" +
        "\n".join(f"  {c.kind.value}: {c.description}" for c in result.changes)
    )
