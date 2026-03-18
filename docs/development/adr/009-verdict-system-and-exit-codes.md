# ADR-009: Verdict System and Exit Code Contract

**Date:** 2026-03-18
**Status:** Accepted
**Decision maker:** Nikolay Petrov

---

## Context

abicheck needs to communicate the outcome of an ABI comparison both to humans
(via reports) and to machines (via exit codes). Two key questions must be
answered:

1. **What severity tiers exist?** Reference tools use simple binary models:
   ABICC uses "compatible / incompatible", libabigail uses "no ABI change /
   ABI change." Neither distinguishes source-level breaks from binary breaks,
   and neither flags deployment-only risks.

2. **What exit codes should the tool return?** ABICC uses 0/1 (compatible /
   incompatible). A richer exit code scheme enables CI pipelines to distinguish
   severity without parsing output.

### Requirements

- Distinguish binary ABI breaks (existing binaries crash) from source-level
  breaks (recompilation required)
- Flag deployment risks that are binary-compatible but may cause load failures
  on older systems
- Exit codes must be composable for multi-library scenarios (ADR-002)
- Different commands may need different exit code schemes for backward
  compatibility

---

## Decision

### 1. Five-tier verdict system

| Verdict | Meaning | Severity |
|---------|---------|----------|
| `NO_CHANGE` | Identical ABI surfaces | None |
| `COMPATIBLE` | Only safe changes (additions, informational drift) | None |
| `COMPATIBLE_WITH_RISK` | Binary-compatible but deployment risk present | Warning |
| `API_BREAK` | Source-level break — recompilation required | Error |
| `BREAKING` | Binary ABI break — existing binaries will crash or fail to load | Critical |

The `COMPATIBLE_WITH_RISK` tier is novel — neither ABICC nor libabigail has an
equivalent. It captures cases like:

- New `GLIBC_2.34` symbol version requirement (library works but won't load on
  older systems)
- Sentinel/MAX enum value changed (binary-safe but source code using it as
  array size may overflow)
- Symbol leaked from a dependency changed (dependency versioning issue, not
  library's own API)

### 2. Exit code contract for `compare`

| Exit code | Verdict | Rationale |
|-----------|---------|-----------|
| **0** | NO_CHANGE, COMPATIBLE, COMPATIBLE_WITH_RISK | Binary-compatible — safe to deploy |
| **2** | API_BREAK | Source-level break only |
| **4** | BREAKING | Binary ABI break |
| **1** | (conditional) | Only when `--fail-on-additions` is set and additions are detected |

Exit codes use powers of 2 to enable bitwise OR composition in multi-library
scenarios (ADR-002):

```text
compare-release result:
  libfoo.so → BREAKING (4)
  libbar.so → API_BREAK (2)
  libbaz.so → COMPATIBLE (0)
  Aggregate: 4 | 2 = 6  →  "at least one BREAKING + at least one API_BREAK"
```

Additional exit codes for `compare-release`:
- **8**: Missing/unmatched libraries (when `--fail-on-removed-library` is set)

### 3. Exit code contract for `compat` (ABICC compatibility)

| Exit code | Verdict | Rationale |
|-----------|---------|-----------|
| **0** | NO_CHANGE, COMPATIBLE, COMPATIBLE_WITH_RISK | ABICC-compatible "no break" |
| **1** | BREAKING | ABICC-compatible "incompatible" (with `-strict`, also promotes COMPATIBLE and API_BREAK) |
| **2** | API_BREAK | Source-level break |
| **3–11** | Error conditions | ABICC-compatible error codes: 3=missing tool, 4=file access, 5=header parse, 6=invalid input, 7=write failure, 8=analysis failure, 10=internal error, 11=interrupted |

The `compat` command uses ABICC's exit code scheme (0/1 for compat/incompat)
to support drop-in migration. The `compare` command uses the richer scheme
(0/2/4) for new integrations.

### 4. Exit code contract for `stack-check`

| Exit code | Verdict | Rationale |
|-----------|---------|-----------|
| **0** | PASS | Binary loads and no harmful ABI changes |
| **1** | WARN | Binary may load but ABI risks detected |
| **4** | FAIL | Binary will not load or has breaking ABI changes |

### 5. Verdict computation

Implemented in `checker_policy.py:compute_verdict()`:

```python
def compute_verdict(changes, *, policy="strict_abi") -> Verdict:
    kinds = {c.kind for c in changes}
    if kinds & breaking_set:
        return Verdict.BREAKING
    if kinds & api_break_set:
        return Verdict.API_BREAK
    if kinds & risk_set:
        return Verdict.COMPATIBLE_WITH_RISK
    if kinds <= compatible_set:
        return Verdict.COMPATIBLE
    # Unclassified kinds → BREAKING (fail-safe)
    return Verdict.BREAKING
```

**Fail-safe default**: Any `ChangeKind` not explicitly classified in any kind
set is treated as BREAKING. This ensures that adding a new detector without
classifying its output produces a visible failure, not a silent pass.

**Display independence**: The verdict is always computed on the full set of
unsuppressed changes, regardless of `--show-only` filters or `--report-mode`.
Display filtering is cosmetic; exit codes are authoritative.

---

## Consequences

### Positive

- CI pipelines can distinguish "recompile needed" (2) from "binaries will
  crash" (4) without parsing output
- `COMPATIBLE_WITH_RISK` surfaces deployment concerns that ABICC silently
  ignores
- Bitwise OR composition enables multi-library aggregate exit codes
- ABICC migration path preserved through `compat` command's exit code scheme
- Fail-safe default prevents new detectors from silently passing

### Negative

- Two exit code schemes (`compare` vs `compat`) add cognitive load
- `COMPATIBLE_WITH_RISK` at exit code 0 means some risks are invisible to
  scripts that only check exit codes — users must read reports for risk details
- Exit code 1 is overloaded: `--fail-on-additions` in `compare`, BREAKING in
  `compat`

---

## References

- `abicheck/checker_policy.py` — `Verdict` enum, `compute_verdict()`,
  `policy_kind_sets()`
- `abicheck/cli.py` — Exit code handling for `compare`, `compare-release`,
  `stack-check`
- `abicheck/compat/cli.py` — ABICC-compatible exit codes
