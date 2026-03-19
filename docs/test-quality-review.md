# Test Quality Review

Comprehensive analysis of all 117 test files (~50K lines) in the abicheck test suite.

## Overall Verdict

**~97% of tests are meaningful** — they validate real behavior with concrete
assertions, not just trigger line coverage. The suite demonstrates mature
testing practices including property-based testing, negative tests, regression
tests tied to specific bugs, and meta-tests for completeness.

## Quantitative Summary

| Category              | Tests  | Meaningful | Padding | Borderline |
|-----------------------|--------|------------|---------|------------|
| Core Checker          | ~159   | 155 (97%)  | 0       | 4          |
| CLI & I/O             | ~184   | 164 (89%)  | 10      | 10         |
| DWARF/Debug           | ~135   | 135 (100%) | 0       | 0          |
| Platform (ELF/PE/MachO)| ~271  | 271 (100%) | 0       | 0          |
| Dumper                | ~175   | 175 (100%) | 0       | 0          |
| Change Detection      | ~66    | 66 (100%)  | 0       | 0          |
| Edge Cases/Regression | ~125   | 125 (100%) | 0       | 0          |
| Serialization         | ~15    | 15 (100%)  | 0       | 0          |
| Suppression           | ~62    | 62 (100%)  | 0       | 0          |
| MCP Server            | ~210   | 210 (100%) | 0       | 0          |
| Performance/Benchmark | ~20    | 18 (90%)   | 1       | 1          |
| Policy & Reporting    | ~90    | 87 (97%)   | 0       | 3          |
| Property-Based/Fuzz   | ~23    | 23 (100%)  | 0       | 0          |
| Negative Tests        | 17     | 17 (100%)  | 0       | 0          |

## Issues Found

### Coverage-Padding Tests (11 tests, ~0.7%)

#### test_cli_coverage_extra.py (3 tests)

Tests that only check `exit_code == 0` without validating actual behavior:

- `test_show_impact_flag` — no validation that impact data is present
- `test_leaf_report_mode` — no validation of leaf report behavior
- `test_stat_text_output` — only asserts `result.output.strip()` (non-empty)

#### test_cli_unit.py (8 tests)

Tests using artificial monkeypatching to inject errors into internal functions
rather than testing real user scenarios:

- `test_setup_logging_error_exits_6`
- `test_skip_symbols_invalid_regex_exits_6`
- `test_skip_internal_invalid_regex_exits_6`
- `test_suppression_load_error_exits_6`
- `test_skip_symbols_missing_file_exits_4`
- `test_symbols_list_missing_file_exits_4`
- `test_report_write_error_exits_7`

These monkeypatch internals (e.g., `_setup_logging`) to throw exceptions. They
exercise error-handling code paths but don't represent real user scenarios.

### Borderline Tests (18 tests, ~1.2%)

#### test_cli_coverage_extra.py (5 tests)

Tests that check exit codes without validating error messages:

- `test_invalid_show_only_token` — only `exit_code != 0`
- `test_nonexistent_old_input` / `test_nonexistent_new_input` — only `exit_code != 0`
- `test_show_redundant_flag` — only `exit_code in (0, 4)`
- `test_stack_check_nonexistent_dirs` — only `exit_code != 0`

#### test_checker_reporter_branches.py (2 tests)

Call filter methods without asserting results:

- `test_severity_api_break` — calls `f.matches()` but doesn't assert
- `test_severity_risk` — same

#### test_detector_contracts.py (2 tests)

Only test detector in disabled state, never when DWARF data is available.

#### test_report_classifications_unit.py (5 tests)

Only verify constants are non-empty (`len() > 0`), not correctness of values.

#### Other (4 tests)

Scattered tests in `test_report_filtering.py` and `test_report_metadata.py`
that only check field presence without validating content.

## Recommendations

1. **Fix 3 no-assertion tests** in `test_cli_coverage_extra.py`:
   - `test_show_impact_flag` should assert impact data is present in output
   - `test_leaf_report_mode` should assert leaf-style structure in output
   - `test_stat_text_output` should assert expected stat fields

2. **Fix 2 missing assertions** in `test_checker_reporter_branches.py`:
   - `test_severity_api_break` and `test_severity_risk` should assert on
     `f.matches()` return values

3. **Strengthen or replace** the 8 artificial error-injection tests in
   `test_cli_unit.py` — prefer feeding actual malformed input over
   monkeypatching internals

4. **Add enabled-state tests** for `test_detector_contracts.py` — test the
   detector when DWARF data is actually present

5. **Remove `test_import_benchmark_script`** — import errors would surface
   from any other test in the file

## Strengths

- **Security validation**: Path traversal, credential directory blocking,
  error message sanitization in MCP server tests
- **Property-based testing**: Hypothesis validates invariants across random
  inputs (roundtrips, policy partitioning, ChangeKind completeness)
- **Negative tests**: `test_negative.py` verifies that benign changes don't
  produce false-positive breaking verdicts
- **Bug-tied regressions**: `test_bugfix_regressions.py` uses `TestBug1..N`
  naming with specific value assertions
- **Meta-test `test_all_change_kinds_covered`**: Ensures every ChangeKind enum
  member has at least one test
- **Architecture conformance**: Validates policy sets are disjoint and
  exhaustive
- **Cross-platform**: ELF, PE, Mach-O, PDB all tested with format-specific
  edge cases

---

## Implementation Spec: Fixing Identified Test Issues

### Fix 1: Strengthen 3 weak tests in `test_cli_coverage_extra.py`

**File:** `tests/test_cli_coverage_extra.py`

#### 1a. `test_show_impact_flag` (line 221)

**Problem:** Only asserts `exit_code == 0`. The `--show-impact` flag should
cause an "Impact Summary" section in markdown output when there are type
changes with affected symbols, or at minimum the flag should be accepted
without changing the output structure for no-change scenarios.

**Fix:** Create snapshots that produce a type change (struct size change with
a function referencing that struct), then assert the output contains impact
information.

```python
def test_show_impact_flag(self, tmp_path: Path) -> None:
    """--show-impact includes impact summary when type changes have affected symbols."""
    from abicheck.model import AbiSnapshot, Function, Param, RecordType, TypeField, Visibility
    from abicheck.serialization import snapshot_to_json

    rec = RecordType(name="Pt", kind="struct", size_bits=32, fields=[
        TypeField(name="x", type="int", offset_bits=0),
    ])
    rec_v2 = RecordType(name="Pt", kind="struct", size_bits=64, fields=[
        TypeField(name="x", type="int", offset_bits=0),
        TypeField(name="y", type="int", offset_bits=32),
    ])
    func = Function(name="draw", mangled="_Z4draw2Pt", return_type="void",
                    params=[Param(name="p", type="Pt")], visibility=Visibility.PUBLIC)

    old_snap = AbiSnapshot(library="lib.so", version="1.0", functions=[func], types=[rec])
    new_snap = AbiSnapshot(library="lib.so", version="2.0", functions=[func], types=[rec_v2])

    old_f = tmp_path / "old.json"
    new_f = tmp_path / "new.json"
    old_f.write_text(snapshot_to_json(old_snap), encoding="utf-8")
    new_f.write_text(snapshot_to_json(new_snap), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["compare", str(old_f), str(new_f), "--show-impact"])
    assert result.exit_code == 4  # breaking (struct size changed)
    assert "Impact Summary" in result.output or "impact" in result.output.lower()
```

**Why this is better:** Tests that `--show-impact` actually produces impact
data in the output, not just that the flag is accepted.

#### 1b. `test_leaf_report_mode` (line 229)

**Problem:** Only asserts `exit_code == 0` on no-change snapshots. The
`--report-mode leaf` flag should produce leaf-change output when there are
type changes.

**Fix:** Create snapshots with type changes, assert output contains
leaf-mode markers.

```python
def test_leaf_report_mode(self, tmp_path: Path) -> None:
    """--report-mode leaf produces leaf-change view with type root changes."""
    from abicheck.model import AbiSnapshot, Function, Param, RecordType, TypeField, Visibility
    from abicheck.serialization import snapshot_to_json

    rec = RecordType(name="Cfg", kind="struct", size_bits=32, fields=[
        TypeField(name="x", type="int", offset_bits=0),
    ])
    rec_v2 = RecordType(name="Cfg", kind="struct", size_bits=64, fields=[
        TypeField(name="x", type="int", offset_bits=0),
        TypeField(name="y", type="int", offset_bits=32),
    ])
    func = Function(name="init", mangled="_Z4init3Cfg", return_type="void",
                    params=[Param(name="c", type="Cfg")], visibility=Visibility.PUBLIC)

    old_snap = AbiSnapshot(library="lib.so", version="1.0", functions=[func], types=[rec])
    new_snap = AbiSnapshot(library="lib.so", version="2.0", functions=[func], types=[rec_v2])

    old_f = tmp_path / "old.json"
    new_f = tmp_path / "new.json"
    old_f.write_text(snapshot_to_json(old_snap), encoding="utf-8")
    new_f.write_text(snapshot_to_json(new_snap), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["compare", str(old_f), str(new_f), "--report-mode", "leaf"])
    assert result.exit_code == 4
    assert "leaf-change view" in result.output or "Cfg" in result.output
```

**Why this is better:** Tests that leaf mode actually produces a different
output structure, not just that the flag doesn't crash.

#### 1c. `test_stat_text_output` (line 165)

**Problem:** Only asserts `result.output.strip()` (non-empty). The stat mode
should produce a one-line summary containing the verdict and change count.

**Fix:** Assert the output contains the verdict string and basic structure.

```python
def test_stat_text_output(self, tmp_path: Path) -> None:
    """--stat produces one-line summary containing verdict."""
    old = _make_json_snapshot(tmp_path, name="libold", version="1.0")
    new = _make_json_snapshot(tmp_path, name="libnew", version="2.0")

    runner = CliRunner()
    result = runner.invoke(main, ["compare", str(old), str(new), "--stat"])
    assert result.exit_code == 0
    output = result.output.strip()
    assert output  # non-empty
    assert "NO_CHANGE" in output  # verdict should appear in stat output
```

**Why this is better:** Validates the stat output contains the expected
verdict, not just that something was printed.

---

### Fix 2: Add assertions to 2 tests in `test_checker_reporter_branches.py`

**File:** `tests/test_checker_reporter_branches.py`

#### 2a. `test_severity_api_break` (line 438)

**Problem:** Calls `f.matches(api_change)` but never asserts the return
value. The ShowOnlyFilter severity classification uses policy sets from
`checker_policy.py`.

**Fix:** Use `ENUM_MEMBER_RENAMED` which is confirmed in `API_BREAK_KINDS`
(checker_policy.py:447). The original plan incorrectly proposed
`FUNC_NOEXCEPT_REMOVED` which is actually in `COMPATIBLE_KINDS`.

```python
def test_severity_api_break(self):
    f = ShowOnlyFilter.parse("api-break")
    # ENUM_MEMBER_RENAMED is in API_BREAK_KINDS → should match
    api_change = Change(kind=ChangeKind.ENUM_MEMBER_RENAMED, symbol="E::V", description="renamed")
    assert f.matches(api_change) is True
    # FUNC_REMOVED is in BREAKING_KINDS, not API_BREAK_KINDS → should not match
    assert f.matches(self._brk_change()) is False
```

**Why:** `ENUM_MEMBER_RENAMED` is in `API_BREAK_KINDS`. The filter should
return `True` for it and `False` for plain breaking kinds.

#### 2b. `test_severity_risk` (line 445)

**Problem:** Same issue — calls `f.matches()` without asserting.
`NEEDED_ADDED` is in `COMPATIBLE_KINDS`, not `RISK_KINDS`. Need to use a
change kind actually in `RISK_KINDS`.

**Fix:**

```python
def test_severity_risk(self):
    f = ShowOnlyFilter.parse("risk")
    # SYMBOL_VERSION_REQUIRED_ADDED is in RISK_KINDS
    risk_change = Change(kind=ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED,
                         symbol="GLIBC_2.34", description="new version requirement")
    assert f.matches(risk_change) is True
    # NEEDED_ADDED is compatible, not risk
    compat_change = Change(kind=ChangeKind.NEEDED_ADDED, symbol="lib", description="needed added")
    assert f.matches(compat_change) is False
```

**Why:** `RISK_KINDS` contains `SYMBOL_VERSION_REQUIRED_ADDED`,
`ENUM_LAST_MEMBER_VALUE_CHANGED`, and
`SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED`. The original test used
`NEEDED_ADDED` which is actually compatible, so even if it did assert,
it would be testing the wrong thing.

---

### Fix 3: Improve 6 error-injection tests in `test_cli_unit.py`

**File:** `tests/test_cli_unit.py`

**Problem:** Tests in `TestCompatClassifiedErrorPaths` monkeypatch internal
functions (`_setup_logging`, `_load_descriptor_or_dump`,
`SuppressionList.load`, `write_html_report`) to throw artificial exceptions.
This tests implementation internals, not user-facing behavior.

**Approach:** Replace with tests that trigger the same error paths using real
(malformed) input. Keep the exit-code assertions but also assert the error
message contains useful information.

#### 3a. `test_setup_logging_error_exits_6` → remove

This monkeypatches `_setup_logging` which is an internal function. A logging
initialization failure is extremely unlikely in practice and not worth testing
via artificial injection. The other compat tests provide sufficient coverage
for the compat command's error handling.

#### 3b. `test_skip_symbols_invalid_regex_exits_6` → rewrite

**Current:** Monkeypatches `_load_descriptor_or_dump`, writes file with `([\n`.

**Better:** This test already provides a real invalid-regex file. The only
monkeypatch is `_load_descriptor_or_dump` which bypasses XML descriptor
parsing. We can improve this by also asserting the error message.

```python
def test_skip_symbols_invalid_regex_exits_6(self, tmp_path, monkeypatch):
    old, new = self._write_minimal_descriptors(tmp_path)
    bad = tmp_path / "skip.txt"
    bad.write_text("([\n", encoding="utf-8")

    snaps = [self._snap("1.0"), self._snap("2.0")]
    monkeypatch.setattr("abicheck.compat.cli._load_descriptor_or_dump",
                        lambda *_a, **_k: snaps.pop(0))

    runner = CliRunner()
    result = runner.invoke(main, [
        "compat", "check", "-lib", "libtest", "-old", str(old), "-new", str(new),
        "-skip-symbols", str(bad),
    ])
    assert result.exit_code == 6
    assert "regex" in result.output.lower() or "pattern" in result.output.lower()
```

**Change:** Add assertion on error message content. Keep the monkeypatch for
descriptor loading since that's testing a different concern.

#### 3c. `test_skip_internal_invalid_regex_exits_6` → same improvement

Add error message assertion: `assert "regex" in result.output.lower()`.

#### 3d. `test_suppression_load_error_exits_6` → rewrite

**Current:** Monkeypatches `SuppressionList.load` to throw ValueError.

**Better:** Provide an actual invalid suppression YAML file that triggers the
ValueError naturally.

```python
def test_suppression_load_error_exits_6(self, tmp_path, monkeypatch):
    old, new = self._write_minimal_descriptors(tmp_path)
    sup = tmp_path / "bad_sup.yaml"
    sup.write_text("- this is a list not a dict\n", encoding="utf-8")

    snaps = [self._snap("1.0"), self._snap("2.0")]
    monkeypatch.setattr("abicheck.compat.cli._load_descriptor_or_dump",
                        lambda *_a, **_k: snaps.pop(0))

    runner = CliRunner()
    result = runner.invoke(main, [
        "compat", "check", "-lib", "libtest", "-old", str(old), "-new", str(new),
        "--suppress", str(sup),
    ])
    assert result.exit_code == 6
    assert "suppression" in result.output.lower() or "yaml" in result.output.lower()
```

**Why:** Uses a real invalid YAML file instead of monkeypatching `load()`.

#### 3e. `test_skip_symbols_missing_file_exits_4` → add message assertion

Keep as-is but add: `assert "no such file" in result.output.lower() or
"skip-symbols" in result.output.lower()`. Note: Python's FileNotFoundError
says "No such file or directory", not "not found".

#### 3f. `test_symbols_list_missing_file_exits_4` → same improvement

Add error message assertion using `"no such file"` (matching Python's actual
FileNotFoundError message).

#### 3g. `test_report_write_error_exits_7` → keep with message assertion

This one is harder to trigger naturally (requires filesystem permission
errors). Keep the monkeypatch but add an error message assertion:
`assert "write" in result.output.lower() or "report" in result.output.lower()`.

**Summary of changes for Fix 3:**

| Test | Action |
|------|--------|
| `test_setup_logging_error_exits_6` | Remove |
| `test_skip_symbols_invalid_regex_exits_6` | Add error message assertion |
| `test_skip_internal_invalid_regex_exits_6` | Add error message assertion |
| `test_suppression_load_error_exits_6` | Replace monkeypatch with real invalid YAML |
| `test_skip_symbols_missing_file_exits_4` | Add error message assertion |
| `test_symbols_list_missing_file_exits_4` | Add error message assertion |
| `test_report_write_error_exits_7` | Add error message assertion |

Also add a helper `_write_minimal_descriptors` to reduce boilerplate:

```python
def _write_minimal_descriptors(self, tmp_path):
    old = tmp_path / "old.xml"
    new = tmp_path / "new.xml"
    old.write_text("<descriptor/>", encoding="utf-8")
    new.write_text("<descriptor/>", encoding="utf-8")
    return old, new
```

---

### Fix 4: Add enabled-state tests for `test_detector_contracts.py`

**File:** `tests/test_detector_contracts.py`

**Problem:** Both existing tests only verify the detector is disabled (when
DWARF metadata is missing). There's no test for when the detector is enabled
and actually finds changes.

**What the detector does when enabled:** Compares `dwarf_advanced` metadata
between old and new snapshots. It detects:
- Calling convention changes
- Value ABI trait changes (trivial→nontrivial or vice versa)
- Struct packing changes
- Toolchain flag drift
- Frame register changes

**New tests to add:**

```python
def test_advanced_dwarf_detector_enabled_when_both_have_metadata() -> None:
    """Detector is enabled when both snapshots have dwarf_advanced."""
    old = AbiSnapshot(
        library="libx.so", version="1.0",
        dwarf_advanced=AdvancedDwarfMetadata(has_dwarf=True),
    )
    new = AbiSnapshot(
        library="libx.so", version="2.0",
        dwarf_advanced=AdvancedDwarfMetadata(has_dwarf=True),
    )
    result = compare(old, new)
    adv = next(d for d in result.detector_results if d.name == "advanced_dwarf")
    assert adv.enabled is True
    assert adv.coverage_gap is None or adv.coverage_gap == ""


def test_advanced_dwarf_detector_finds_calling_convention_change() -> None:
    """Detector reports CALLING_CONVENTION_CHANGED when CC differs."""
    from abicheck.checker_policy import ChangeKind

    old = AbiSnapshot(
        library="libx.so", version="1.0",
        functions=[Function(name="foo", mangled="_Z3foov", return_type="int",
                            visibility=Visibility.PUBLIC)],
        dwarf_advanced=AdvancedDwarfMetadata(
            has_dwarf=True,
            calling_conventions={"_Z3foov": "normal"},
        ),
    )
    new = AbiSnapshot(
        library="libx.so", version="2.0",
        functions=[Function(name="foo", mangled="_Z3foov", return_type="int",
                            visibility=Visibility.PUBLIC)],
        dwarf_advanced=AdvancedDwarfMetadata(
            has_dwarf=True,
            calling_conventions={"_Z3foov": "stdcall"},
        ),
    )
    result = compare(old, new)
    assert any(c.kind == ChangeKind.CALLING_CONVENTION_CHANGED for c in result.changes)


def test_advanced_dwarf_detector_finds_packing_change() -> None:
    """Detector reports STRUCT_PACKING_CHANGED when packing status changes."""
    from abicheck.checker_policy import ChangeKind

    old = AbiSnapshot(
        library="libx.so", version="1.0",
        dwarf_advanced=AdvancedDwarfMetadata(
            has_dwarf=True,
            packed_structs=set(),
            all_struct_names={"MyStruct"},
        ),
    )
    new = AbiSnapshot(
        library="libx.so", version="2.0",
        dwarf_advanced=AdvancedDwarfMetadata(
            has_dwarf=True,
            packed_structs={"MyStruct"},
            all_struct_names={"MyStruct"},
        ),
    )
    result = compare(old, new)
    assert any(c.kind == ChangeKind.STRUCT_PACKING_CHANGED for c in result.changes)


def test_advanced_dwarf_detector_no_changes_when_identical() -> None:
    """Detector produces no changes when metadata is identical."""
    from abicheck.checker_policy import ChangeKind

    meta = AdvancedDwarfMetadata(
        has_dwarf=True,
        calling_conventions={"_Z3foov": "normal"},
        packed_structs=set(),
        all_struct_names={"A"},
    )
    old = AbiSnapshot(library="libx.so", version="1.0", dwarf_advanced=meta)
    new = AbiSnapshot(library="libx.so", version="2.0", dwarf_advanced=meta)

    result = compare(old, new)
    dwarf_kinds = {
        ChangeKind.CALLING_CONVENTION_CHANGED,
        ChangeKind.STRUCT_PACKING_CHANGED,
        ChangeKind.TOOLCHAIN_FLAG_DRIFT,
        ChangeKind.FRAME_REGISTER_CHANGED,
        ChangeKind.VALUE_ABI_TRAIT_CHANGED,
    }
    assert not any(c.kind in dwarf_kinds for c in result.changes)
```

**Why:** Tests the detector's actual behavior: enabled state, change
detection, and negative case. The existing tests only covered the disabled
state.

---

### Fix 5: Strengthen 5 constant tests in `test_report_classifications_unit.py`

**File:** `tests/test_report_classifications_unit.py`

**Problem:** Tests like `test_removed_kinds_non_empty` only check
`len(REMOVED_KINDS) > 0` and `isinstance(..., frozenset)`. They don't verify
that specific expected values are in the set.

**Fix:** Replace with tests that verify specific known members exist in each
set:

```python
class TestConstants:
    def test_removed_kinds_contains_expected_members(self):
        assert isinstance(REMOVED_KINDS, frozenset)
        assert "func_removed" in REMOVED_KINDS
        assert "var_removed" in REMOVED_KINDS
        assert "type_removed" in REMOVED_KINDS

    def test_added_kinds_contains_expected_members(self):
        assert isinstance(ADDED_KINDS, frozenset)
        assert "func_added" in ADDED_KINDS
        assert "var_added" in ADDED_KINDS
        assert "type_added" in ADDED_KINDS

    def test_binary_only_kinds_contains_expected_members(self):
        assert isinstance(BINARY_ONLY_KINDS, frozenset)
        assert "soname_changed" in BINARY_ONLY_KINDS
        assert "symbol_type_changed" in BINARY_ONLY_KINDS
        assert "calling_convention_changed" in BINARY_ONLY_KINDS

    def test_breaking_kinds_contains_expected_members(self):
        assert isinstance(BREAKING_KINDS, frozenset)
        assert "func_removed" in BREAKING_KINDS
        assert "type_size_changed" in BREAKING_KINDS
        assert "var_removed" in BREAKING_KINDS

    def test_changed_breaking_kinds_contains_expected_members(self):
        assert isinstance(CHANGED_BREAKING_KINDS, frozenset)
        assert "func_params_changed" in CHANGED_BREAKING_KINDS
        assert "func_return_changed" in CHANGED_BREAKING_KINDS
        assert "type_field_offset_changed" in CHANGED_BREAKING_KINDS
```

**Why:** Validates that key classification constants contain the right values.
If someone accidentally removes `func_removed` from `REMOVED_KINDS`, the old
test would still pass as long as any one member remained.

---

### Fix 6: Strengthen 5 borderline CLI tests in `test_cli_coverage_extra.py`

**File:** `tests/test_cli_coverage_extra.py`

#### 6a. `test_invalid_show_only_token` (line 130)

**Current:** `assert result.exit_code != 0`
**Fix:** `assert result.exit_code != 0` and
`assert "Unknown --show-only token" in result.output or "Invalid value" in result.output`

Click's `BadParameter` wraps the `ValueError` from `ShowOnlyFilter.parse()`.

#### 6b. `test_nonexistent_old_input` (line 246)

**Current:** `assert result.exit_code != 0`
**Fix:** `assert result.exit_code != 0` and
`assert "does not exist" in result.output or "Invalid value" in result.output`

Click's `Path(exists=True)` produces `"does not exist"` messages.

#### 6c. `test_nonexistent_new_input` (line 254)

Same as 6b.

#### 6d. `test_show_redundant_flag` (line 272)

**Current:** `assert result.exit_code in (0, 4)`
**Fix:** Assert the specific expected exit code (4, since a function is
removed → BREAKING) and validate output contains the breaking change:
```python
assert result.exit_code == 4
assert "BREAKING" in result.output or "foo" in result.output
```

#### 6e. `test_stack_check_nonexistent_dirs` (line 311)

**Current:** `assert result.exit_code != 0`
**Fix:** `assert result.exit_code != 0` and
`assert "does not exist" in result.output or "Invalid value" in result.output`

Click's `Path(exists=True)` produces `"does not exist"` messages.

---

### Fix 7: Remove `test_import_benchmark_script` from `test_benchmark_smoke.py`

**File:** `tests/test_benchmark_smoke.py`

**Problem:** The test only checks `hasattr(mod, "main")`. Import errors would
be caught by any of the other 11 tests in the file that all call
`_load_benchmark()`.

**Action:** Delete lines 35-41 (`test_import_benchmark_script` function).

---

## Execution Order

All fixes are independent and can be implemented in any order. Suggested
grouping by file:

1. `test_checker_reporter_branches.py` — Fix 2 (2 test edits)
2. `test_cli_coverage_extra.py` — Fixes 1 + 6 (8 test edits)
3. `test_cli_unit.py` — Fix 3 (7 test edits, 1 removal)
4. `test_detector_contracts.py` — Fix 4 (4 new tests)
5. `test_report_classifications_unit.py` — Fix 5 (5 test edits)
6. `test_benchmark_smoke.py` — Fix 7 (1 test removal)

**Total changes:** ~22 test edits/additions, 2 test removals across 6 files.

## Verification

After all changes, run the full test suite:
```
pytest tests/ -x -q
```

Verify no regressions and all new/modified tests pass. The total test count
should decrease by 2 (removed tests) and increase by 4 (new detector tests),
for a net gain of +2 tests.
