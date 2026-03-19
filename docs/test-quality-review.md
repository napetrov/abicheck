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
