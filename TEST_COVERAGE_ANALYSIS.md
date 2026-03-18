# Test Coverage Analysis — abicheck

**Date:** 2026-03-18
**Overall Coverage:** 90.6% line coverage (9,296 statements, 678 missed)
**Tests:** 2,739 passing, 6 skipped, 189 deselected (integration)

## Modules Below 90% Coverage

| Module | Stmts | Missed | Cover | Key Gaps |
|--------|------:|-------:|------:|----------|
| compat/cli.py | 532 | 85 | 81.9% | ABICC compat CLI paths, error handling |
| mcp_server.py | 287 | 50 | 82.2% | Server init, tool handlers |
| cli.py | 781 | 115 | 82.3% | `deps`/`stack-check` subcommands, error paths |
| compat/abicc_dump_import.py | 148 | 19 | 83.8% | Perl dump format edge cases |
| dwarf_advanced.py | 409 | 51 | 85.2% | Calling conventions, packing analysis |
| pdb_utils.py | 117 | 14 | 85.3% | PDB utility edge cases |
| dwarf_snapshot.py | 500 | 51 | 85.6% | DWARF-to-snapshot conversion branches |
| dwarf_unified.py | 47 | 6 | 86.8% | Fallback paths |
| stack_report.py | 122 | 11 | 87.2% | Report formatting branches |
| macho_metadata.py | 142 | 10 | 87.2% | Mach-O parsing edge cases |
| pdb_metadata.py | 129 | 14 | 88.1% | PDB metadata extraction |
| binder.py | 131 | 7 | 89.8% | Symbol binding edge cases |

## Gap Categories

### 1. CLI Layer (cli.py: 82.3%, compat/cli.py: 81.9%)
- `deps` subcommand (~lines 1222-1292) and `stack-check` have minimal coverage
- Error handling paths (malformed input, missing files) largely untested
- **Fix:** Add CliRunner tests for `deps`, `stack-check`, and error scenarios

### 2. MCP Server (mcp_server.py: 82.2%)
- Server initialization, tool handlers for `compare`/`dump` uncovered
- **Fix:** Unit tests mocking the MCP framework

### 3. DWARF Analysis (dwarf_advanced: 85.2%, dwarf_snapshot: 85.6%)
- Calling convention detection, packing analysis, incomplete DWARF fallbacks
- **Fix:** Synthetic DWARF fixture data targeting uncovered branches

### 4. Windows/macOS Modules (pdb_utils: 85.3%, pdb_metadata: 88.1%, macho: 87.2%)
- Platform-specific error/edge-case paths
- **Fix:** Mock-based unit tests; fixture-based tests with pre-captured metadata

### 5. Stack Analysis (stack_report: 87.2%, binder: 89.8%)
- Report formatting branches, versioned/weak symbol binding
- **Fix:** Targeted unit tests for edge cases

### 6. ABICC Compat (compat/abicc_dump_import: 83.8%)
- Perl dump format malformed/legacy inputs
- **Fix:** Edge-case Perl dump test data

## Structural Gaps (Beyond Line Coverage)

1. **No property-based testing** — Hypothesis is in deps but unused; valuable for serialization roundtrips, policy classification, type comparison
2. **No adversarial input tests** — Malformed binaries, truncated DWARF, corrupted PDB
3. **No performance benchmarks in CI** — benchmark_comparison.py exists but isn't automated
4. **Branch coverage gaps** — 426 partial branches missed, worst in dwarf_snapshot (53), checker (37), cli (34), reporter (26)

## Priority Plan

| Pri | Action | Impact | Effort |
|-----|--------|--------|--------|
| P0 | CLI tests for `deps`/`stack-check` | +2-3% | Medium |
| P0 | MCP server handler tests | +1-2% | Medium |
| P1 | DWARF edge case fixtures | +1-2% | High |
| P1 | PDB/Mach-O mock edge tests | +1% | Medium |
| P2 | Hypothesis property tests | Bug finding | Medium |
| P2 | Branch coverage in checker/reporter | Quality | Medium |
| P3 | Adversarial/malformed input tests | Robustness | High |

Addressing P0+P1 would push coverage to ~94-95%.
