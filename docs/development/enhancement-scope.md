# Enhancement Scope: Partially Implemented Items

**Date:** 2026-03-23
**Purpose:** Detailed implementation scope for each enhancement identified in the evaluation

---

## 1. Baseline Pinning Workflow

**Current state:** Snapshots (`abicheck dump`) produce JSON files with `schema_version: 3`.
Comparison (`abicheck compare`) accepts two file paths. The GitHub Action has a
`baseline` input but only for `stack-check` mode (filesystem sysroot, not a snapshot
reference). Users manually download baselines in CI via `gh release download`.

**Gap:** No `abicheck baseline` command. No automatic discovery of "the right baseline"
from git tags, GitHub Releases, or a local registry.

### Scope

#### 1a. Provenance metadata in snapshots (schema v4)

| Item | Detail |
|------|--------|
| **What** | Add optional fields to `AbiSnapshot`: `git_commit`, `git_tag`, `created_at` (ISO 8601), `ci_run_id` |
| **Files** | `model.py` (dataclass), `serialization.py` (bump `SCHEMA_VERSION` to 4, serialize/deserialize new fields) |
| **Compat** | Old snapshots (v1–v3) load unchanged — new fields default to `None`. Forward-reading (v4 by old tool) already emits a warning and proceeds. |
| **Tests** | Roundtrip test for v4 fields. Verify v3 snapshot still loads cleanly against v4 code. |
| **Size** | ~80 lines model + serialization, ~40 lines tests |

#### 1b. `abicheck baseline save` / `abicheck baseline show` subcommands

| Item | Detail |
|------|--------|
| **What** | `baseline save` wraps `dump` + writes snapshot to a conventional path (`.abicheck/baselines/<lib>-<tag>.json`) and optionally updates a `.abicheck/baselines/index.yaml` manifest. `baseline show` prints the current pinned baseline for a library. |
| **Files** | New module `abicheck/baseline.py` (~200 lines). CLI wiring in `cli.py` (~60 lines). |
| **Design choice** | File-based registry (no database). Index is optional — compare can also accept a raw path. |
| **Tests** | Unit tests for save/show/index CRUD. Integration test: dump → save → compare round-trip. |
| **Size** | ~260 lines implementation, ~120 lines tests |

#### 1c. `--baseline` convenience flag on `compare`

| Item | Detail |
|------|--------|
| **What** | `abicheck compare --baseline latest ./build/libfoo.so -H include/foo.h` resolves the old-input automatically from the index or from git tags. Accepts `latest`, `stable`, or a semver/tag string. |
| **Files** | `cli.py` (new option + resolver call), `baseline.py` (resolution logic) |
| **Prerequisite** | 1b |
| **Size** | ~60 lines |

#### 1d. GitHub Action `baseline: latest-release` input

| Item | Detail |
|------|--------|
| **What** | New action input `baseline` (values: `latest-release`, `<tag>`, file path). `run.sh` uses `gh release download` to fetch the matching snapshot asset. |
| **Files** | `action.yml`, `action/run.sh` |
| **Prerequisite** | Snapshot must be uploaded as a release asset (documented recipe) |
| **Size** | ~40 lines shell |

#### Priority order: 1a → 1b → 1c → 1d

**Total estimate:** ~440 lines implementation, ~160 lines tests, schema version bump.

---

## 2. MCP Auth Hardening

**Current state:** Stdio-only transport (JSON-RPC over stdin/stdout). No network
listener. Strong path safety (`_safe_write_path` with extension whitelist + system
directory blocklist + credential directory blocklist). Error sanitization prevents
path leakage. No authentication layer because stdio inherits process-level access.

**Gap:** If MCP ever moves to SSE/HTTP transport, there is no auth mechanism. No
formal ADR documents the security model. No loopback enforcement docs.

### Scope

#### 2a. ADR for MCP Security Model

| Item | Detail |
|------|--------|
| **What** | Formal ADR documenting: (1) stdio-only transport as deliberate choice, (2) path safety rationale, (3) error sanitization design, (4) when/how to add auth if networked mode is introduced. |
| **Files** | `docs/development/adr/021-mcp-security-model.md` |
| **Size** | ~120 lines |

#### 2b. Loopback enforcement for future networked mode

| Item | Detail |
|------|--------|
| **What** | Add a `--transport` flag to `abicheck-mcp` (values: `stdio` (default), `sse`). When `sse`, bind to `127.0.0.1` only. Add `--auth-token` flag that enables Bearer token validation on every request. If `--transport sse` is used without `--auth-token`, emit a warning. |
| **Files** | `mcp_server.py` (~80 lines: transport selection, token middleware) |
| **Prerequisite** | ADR-021 accepted |
| **Risk** | FastMCP `>=1.2.0` may not support SSE natively — verify before implementing. If not, this becomes "design only" in the ADR. |
| **Size** | ~80 lines implementation, ~60 lines tests |

#### 2c. Operation timeout and resource limits

| Item | Detail |
|------|--------|
| **What** | Add configurable timeout (default 120s) for `abi_dump` and `abi_compare` tool calls. Add max input file size check (default 500 MB). |
| **Files** | `mcp_server.py` (~40 lines) |
| **Size** | ~40 lines implementation, ~30 lines tests |

#### 2d. Audit logging

| Item | Detail |
|------|--------|
| **What** | Log every tool invocation (tool name, input paths, duration, verdict) at INFO level to stderr. Structured JSON format when `--log-format json` is passed. |
| **Files** | `mcp_server.py` (~50 lines) |
| **Size** | ~50 lines implementation, ~20 lines tests |

#### Priority order: 2a → 2c → 2d → 2b

**Total estimate:** ~290 lines implementation, ~110 lines tests, 1 ADR.

---

## 3. Snapshot Schema Backward-Compat Testing

**Current state:** `SCHEMA_VERSION = 3` in `serialization.py`. Deserialization defaults
missing `schema_version` to v1. Future versions (>3) emit `UserWarning` and attempt
best-effort load. Tests exist for v1 (missing field), v3 (current), and v999 (future
warning). No explicit test for v2. No golden snapshot files at each schema version.

**Gap:** No golden v1/v2 snapshot fixtures. No explicit v2 test. No test that loads a
real old-format snapshot and verifies the full comparison pipeline still works.

### Scope

#### 3a. Golden snapshot fixtures per schema version

| Item | Detail |
|------|--------|
| **What** | Create `tests/fixtures/schema/v1.json` (no `schema_version` key), `v2.json` (`schema_version: 2`), `v3.json` (`schema_version: 3`) with a minimal but representative snapshot (2 functions, 1 type, ELF metadata). |
| **Files** | 3 JSON fixture files (~50 lines each) |
| **Size** | ~150 lines fixtures |

#### 3b. Parameterized load tests

| Item | Detail |
|------|--------|
| **What** | `@pytest.mark.parametrize` test that loads each golden fixture, verifies it deserializes to a valid `AbiSnapshot`, and that `compare(v_N, v_N)` returns `NO_CHANGE`. |
| **Files** | `tests/test_schema_compat.py` (~80 lines) |
| **Size** | ~80 lines tests |

#### 3c. Cross-version comparison test

| Item | Detail |
|------|--------|
| **What** | Load v1 fixture and v3 fixture (same logical content, different schema), run `compare()`, verify `NO_CHANGE`. This proves schema migration is transparent to the comparison engine. |
| **Files** | Same test file |
| **Size** | ~30 lines |

#### 3d. Reserialization stability test

| Item | Detail |
|------|--------|
| **What** | Load v1 fixture → `snapshot_to_dict()` → verify output has `schema_version: 3` (always writes current). Confirm no data loss by comparing fields. |
| **Files** | Same test file |
| **Size** | ~20 lines |

#### Priority order: 3a → 3b → 3c → 3d (all in one PR)

**Total estimate:** ~150 lines fixtures, ~130 lines tests. No production code changes.

---

## 4. Diffoscope Integration

**Current state:** Zero references to diffoscope in the codebase. abicheck uses its own
three-pass analysis (ELF symbols + castxml AST + DWARF debug info) which is more
granular than diffoscope for ABI-specific changes. Diffoscope provides byte-level and
section-level diffs that abicheck does not.

**Gap:** When abicheck reports a breaking change, users sometimes want a low-level
byte diff to understand *exactly* what changed in the binary. Diffoscope fills this
niche but is not integrated.

### Scope

#### 4a. Optional diffoscope attachment on failure

| Item | Detail |
|------|--------|
| **What** | New `--diffoscope` flag on `compare` and `compare-release`. When the verdict is `API_BREAK` or `BREAKING`, shell out to `diffoscope --text -` and capture output. Attach as `diffoscope_output` field in JSON report, or as a collapsed `<details>` block in Markdown/HTML. |
| **Files** | `cli.py` (~30 lines flag + conditional call), new `abicheck/diffoscope_bridge.py` (~60 lines subprocess wrapper + output capture) |
| **Prerequisite** | `diffoscope` installed on PATH (not a Python dependency — optional external tool). |
| **Error handling** | If `diffoscope` not found, emit warning and skip. If it times out (default 60s), emit warning and skip. Never fail the overall command due to diffoscope errors. |
| **Size** | ~90 lines implementation, ~40 lines tests (mock subprocess) |

#### 4b. Documentation

| Item | Detail |
|------|--------|
| **What** | Add section to `docs/user-guide/local-compare.md` explaining when to use `--diffoscope` and how to install it. |
| **Size** | ~30 lines docs |

#### Priority: Single PR, low urgency

**Total estimate:** ~90 lines implementation, ~40 lines tests, ~30 lines docs.

---

## 5. Parallel Diff / Caching

**Current state:** `_compare_release_libraries()` in `cli.py` iterates over matched
library pairs **sequentially**. Each pair is independent (no shared state mutation).
`_diff_stacks()` in `stack_checker.py` also loops sequentially over changed DSOs.
AST-level caching exists (`~/.cache/abi_check/castxml/`) but no snapshot-level cache.

**Gap:** For packages with 5–20 shared libraries, comparison is O(N) sequential.
No snapshot caching means repeated comparisons of the same binary recompute from scratch.

### Scope

#### 5a. `--jobs N` flag for `compare-release`

| Item | Detail |
|------|--------|
| **What** | Add `--jobs` / `-j` option (default 1). When N > 1, use `concurrent.futures.ProcessPoolExecutor(max_workers=N)` in `_compare_release_libraries()`. Each `_run_compare_pair()` call becomes a future. Results aggregated after `as_completed()`. |
| **Files** | `cli.py` (~50 lines: flag, executor setup, future collection, error handling) |
| **Thread safety** | Each pair operates on separate file paths — no shared mutable state. Logging uses thread-safe `logging` module. |
| **Constraint** | castxml subprocess calls are the bottleneck — `ProcessPoolExecutor` avoids GIL. `ThreadPoolExecutor` is insufficient for CPU-bound AST parsing. |
| **Tests** | Test with `--jobs 2` on a 2-library fixture. Verify identical results to `--jobs 1`. |
| **Size** | ~50 lines implementation, ~40 lines tests |

#### 5b. `--jobs N` flag for `stack-check`

| Item | Detail |
|------|--------|
| **What** | Same pattern applied to `_diff_stacks()` loop. Prerequisite: graph resolution must complete first (sequential), then per-library diffs run in parallel. |
| **Files** | `stack_checker.py` (~40 lines) |
| **Prerequisite** | 5a (shared executor pattern) |
| **Size** | ~40 lines implementation, ~30 lines tests |

#### 5c. Snapshot caching layer

| Item | Detail |
|------|--------|
| **What** | New `abicheck/snapshot_cache.py` (~120 lines). Cache key = SHA256(binary content hash + header mtimes + include dir listing + compiler params). Cache location = `~/.cache/abi_check/snapshots/<key>.json`. `--no-cache` flag to bypass. Cache eviction: LRU by mtime, configurable max entries (default 100). |
| **Files** | New `snapshot_cache.py`, integration in `cli.py` (`_resolve_input` calls cache lookup first) |
| **Invalidation** | Binary mtime changed → miss. Header mtime changed → miss. Compiler flags changed → different key entirely. |
| **Tests** | Cache hit/miss roundtrip. Invalidation on binary change. `--no-cache` bypass. |
| **Size** | ~120 lines implementation, ~60 lines tests |

#### 5d. GitHub Action `jobs` input

| Item | Detail |
|------|--------|
| **What** | Expose `--jobs` via `jobs` input in `action.yml`. Default to `0` (auto-detect CPU count) for `compare-release` mode. |
| **Files** | `action.yml`, `action/run.sh` |
| **Size** | ~10 lines |

#### Priority order: 5c → 5a → 5d → 5b

**Total estimate:** ~210 lines implementation, ~130 lines tests.

---

## 6. Naming Collision Clarity

**Current state:** The PyPI package, CLI entry point, and Python module are all named
`abicheck`. Some Linux distributions ship an unrelated `abicheck` tool (Debian's
`devscripts` package includes `abi-compliance-checker` wrapper scripts; Fedora has
`abicheck` in `libabigail-tools`). The project README and docs do not address this.

**Gap:** Users who `pip install abicheck` on a system with a distro `abicheck` may
get confused about which tool is running. No disambiguation guidance exists.

### Scope

#### 6a. Documentation clarification

| Item | Detail |
|------|--------|
| **What** | Add "Naming" section to README.md and `docs/user-guide/install.md` explaining: (1) this project is distinct from distro `abicheck`/`abi-compliance-checker`, (2) `pip install abicheck` installs the Python-based tool, (3) check `abicheck --version` to confirm, (4) if conflict exists, use `python -m abicheck` as an alternative entry point. |
| **Files** | `README.md` (~15 lines), `docs/user-guide/install.md` (~20 lines) |
| **Size** | ~35 lines docs |

#### 6b. `python -m abicheck` entry point

| Item | Detail |
|------|--------|
| **What** | Add `abicheck/__main__.py` (3 lines: `from .cli import main; main()`) so `python -m abicheck` works as an alternative when the `abicheck` script name conflicts. |
| **Files** | New `abicheck/__main__.py` (3 lines) |
| **Tests** | Verify `python -m abicheck --version` returns correct version. |
| **Size** | 3 lines implementation, ~5 lines test |

#### 6c. `--version` output enhancement

| Item | Detail |
|------|--------|
| **What** | Change `abicheck --version` output from `abicheck, version 0.2.0` to `abicheck 0.2.0 (napetrov/abicheck)` to disambiguate from distro tools. |
| **Files** | `cli.py` (~3 lines) |
| **Size** | ~3 lines |

#### Priority order: 6b → 6c → 6a (all in one PR)

**Total estimate:** ~6 lines implementation, ~5 lines tests, ~35 lines docs.

---

## Summary Matrix

| # | Enhancement | Impl Lines | Test Lines | Doc Lines | Priority | Complexity |
|---|-------------|-----------|-----------|----------|----------|------------|
| 1 | Baseline pinning | ~440 | ~160 | ~40 | Medium | High |
| 2 | MCP auth hardening | ~290 | ~110 | ~120 | Medium | Medium |
| 3 | Schema compat tests | 0 | ~130 | 0 | Low | Low |
| 4 | Diffoscope integration | ~90 | ~40 | ~30 | Low | Low |
| 5 | Parallel diff / caching | ~210 | ~130 | ~10 | Medium | Medium |
| 6 | Naming collision | ~6 | ~5 | ~35 | Low | Trivial |

### Recommended implementation order

1. **Schema compat tests (3)** — Zero production code risk, fills a testing gap, fast win
2. **Naming collision (6)** — Trivial, high user-facing value for confused users
3. **Parallel diff / caching (5)** — Start with 5c (cache) for immediate speedup, then 5a (parallel)
4. **MCP auth hardening (2)** — Start with 2a (ADR) to lock down the design, then 2c/2d
5. **Baseline pinning (1)** — Largest scope; start with 1a (provenance metadata) as foundation
6. **Diffoscope integration (4)** — Nice-to-have, lowest urgency
