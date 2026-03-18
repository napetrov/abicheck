# abicheck Bug Report

**Tool version:** 0.2.0
**Platform:** Linux x86_64 (Ubuntu 24.04, GCC 13.3.0, castxml 0.6.3)
**Date:** 2026-03-18

## Summary

Testing abicheck against real compiled shared libraries with various use cases
uncovered **7 confirmed bugs** (1 was reclassified after code review). Each bug
includes root cause analysis with exact file locations and line numbers.

| # | Severity | Bug | Root Cause Location |
|---|----------|-----|---------------------|
| 1 | HIGH | Duplicate enum change detection | `checker.py:1772-1779` — missing enum entries in `_DWARF_TO_AST_EQUIV` |
| 2 | MEDIUM | Raw Python repr in `func_params_changed` | `checker.py:218-219` — `str()` on list of tuples containing `ParamKind` enum |
| 3 | MEDIUM | Snapshot metadata shows JSON file info | `cli.py:1070-1071` — `_collect_metadata()` called on `.json` path |
| 4 | MEDIUM | Policy overrides don't affect report sections | `checker.py:2273` — only base policy name stored, overrides lost |
| 5 | MEDIUM | Unhandled exception on missing output dir | `cli.py:1103` — no directory existence check before `write_text()` |
| 6 | ~~LOW~~ | ~~compare-release picks up .o files~~ | **RECLASSIFIED: Not a bug** (see below) |
| 7 | MEDIUM | `deps` reports PASS for non-ELF files | `resolver.py:267` — no ELF validation; empty metadata → false PASS |
| 8 | MEDIUM | `affected_pct` always 0.0 | `report_summary.py:71` — `old_symbol_count` never passed to `compatibility_metrics()` |

---

## Bug 1: Duplicate Enum Change Detection (HIGH)

**Command:**
```bash
abicheck compare v1/libenum.so v2/libenum.so \
  --old-header v1/libenum.h --new-header v2/libenum.h
```

**Problem:** Each enum member value change is reported **twice** — once from the
header/AST-based detector (symbol=`Color`) and once from the DWARF-based detector
(symbol=`Color::GREEN`). The two entries have slightly different formats but
describe the same semantic change.

**Reproduction JSON output:**
```
enum_member_value_changed  symbol=Color          old=1 new=2  (from AST)
enum_member_value_changed  symbol=Color          old=2 new=3  (from AST)
enum_member_value_changed  symbol=Color::GREEN   old=1 new=2  (from DWARF)
enum_member_value_changed  symbol=Color::BLUE    old=2 new=3  (from DWARF)
```

**Root Cause:** `checker.py:1772-1779` — The `_DWARF_TO_AST_EQUIV` deduplication
map has entries for struct changes but **no entries for enum changes**:

```python
_DWARF_TO_AST_EQUIV: dict[ChangeKind, set[ChangeKind]] = {
    ChangeKind.STRUCT_SIZE_CHANGED: {ChangeKind.TYPE_SIZE_CHANGED},
    ChangeKind.STRUCT_ALIGNMENT_CHANGED: {ChangeKind.TYPE_ALIGNMENT_CHANGED},
    ChangeKind.STRUCT_FIELD_OFFSET_CHANGED: {ChangeKind.TYPE_FIELD_OFFSET_CHANGED},
    ChangeKind.STRUCT_FIELD_REMOVED: {ChangeKind.TYPE_FIELD_REMOVED},
    ChangeKind.STRUCT_FIELD_TYPE_CHANGED: {ChangeKind.TYPE_FIELD_TYPE_CHANGED},
    # NO ENUM ENTRIES — this is the gap
}
```

The deduplication function `_deduplicate_ast_dwarf()` at line 2114-2151 uses two
strategies, both of which fail for enums:
1. **Exact dedup** (line 2137): Fails because descriptions differ (`"Color::GREEN"`
   vs `"Color::GREEN (1 → 2)"`)
2. **Cross-kind dedup** (line 2145): Fails because no enum kinds are in the map

**Detection paths:**
- AST: `_diff_enums()` at line 602-678, sets `symbol=name` (enum type name)
- DWARF: `_diff_enum_layouts()` at line 2762-2841, sets `symbol=f"{name}::{mname}"`

**Impact:** Inflated breaking change counts (4 reported instead of 2), misleading
CI gate decisions.

---

## Bug 2: `func_params_changed` Shows Raw Python Repr in C Mode (MEDIUM)

**Command:**
```bash
abicheck compare v1/libtest.so v2/libtest.so \
  --old-header v1/libtest.h --new-header v2/libtest.h --lang c
```

**Problem:** Parameter change description exposes internal Python types:
```
Parameters changed: multiply
  (`[('int', <ParamKind.VALUE: 'value'>), ('int', <ParamKind.VALUE: 'value'>)]`
   → `[('long int', <ParamKind.VALUE: 'value'>), ('long int', <ParamKind.VALUE: 'value'>)]`)
```

**Root Cause:** `checker.py:211-220` — The code creates tuples of `(p.type, p.kind)`
where `p.kind` is a `ParamKind` enum, then calls `str()` on the list:

```python
old_params = [(p.type, p.kind) for p in f_old.params]
new_params = [(p.type, p.kind) for p in f_new.params]
if old_params != new_params:
    changes.append(Change(
        kind=ChangeKind.FUNC_PARAMS_CHANGED,
        symbol=mangled,
        description=f"Parameters changed: {f_old.name}",
        old_value=str(old_params),      # BUG: includes ParamKind enum repr
        new_value=str(new_params),      # BUG: same
    ))
```

`ParamKind` is defined in `model.py:45` as `class ParamKind(str, Enum)`. While it
inherits from `str`, when used inside a tuple and converted via `str()`, Python
shows the full enum repr `<ParamKind.VALUE: 'value'>` instead of just `'value'`.

**Expected:** Human-readable output like `int, int → long int, long int`.

---

## Bug 3: Snapshot Comparison Shows JSON File Metadata Instead of Library Metadata (MEDIUM)

**Command:**
```bash
abicheck dump v1/libtest.so -H v1/libtest.h --version 1.0 -o baseline.json
abicheck compare baseline.json v2/libtest.so --new-header v2/libtest.h
```

**Problem:** The "Library Files" section shows the JSON snapshot's path, SHA-256,
and file size instead of the original library's metadata.

**Root Cause:** `cli.py:1070-1071` — `_collect_metadata()` is called on the input
path, which is the `.json` file:

```python
old_metadata = _collect_metadata(old_input)   # old_input = "baseline.json"
new_metadata = _collect_metadata(new_input)
```

`_collect_metadata()` at line 355-364 computes `sha256` and `size_bytes` from the
raw file bytes — so when the input is a JSON file, it hashes/measures the JSON,
not the original library.

The original library metadata is **never stored** in the snapshot format
(`serialization.py:61-101`). Only `library` name and `version` are preserved,
not the source file's path/size/hash. So even if the code tried to extract it,
the data isn't there.

**Impact:** Misleading metadata in reports — users see 5.2 KB JSON file sizes
instead of 15.9 KB library sizes.

---

## Bug 4: Policy File Override Changes Verdict But Not Report Section Headers (MEDIUM)

**Command:**
```bash
cat > policy.yaml << 'EOF'
version: 1
overrides:
  func_removed: warn
  enum_member_value_changed: ignore
EOF
abicheck compare v1/libenum.so v2/libenum.so \
  --old-header v1/libenum.h --new-header v2/libenum.h \
  --policy-file policy.yaml
```

**Problem:** With `enum_member_value_changed: ignore`, the verdict correctly
becomes `COMPATIBLE` (exit 0), but the report still shows:
- Summary: "Breaking changes: 4"
- Section header: "❌ Breaking Changes"
- Lists all 4 enum changes under that section

The verdict and body are contradictory.

**Root Cause:** `checker.py:2272-2284` — Only the base policy name is stored in
`DiffResult`, not the `PolicyFile` object with overrides:

```python
# Line 2272: Verdict IS computed with overrides (correct)
verdict = policy_file.compute_verdict(all_unsuppressed)

# Line 2273: But only base policy name is stored (overrides lost!)
effective_policy = policy_file.base_policy if policy_file is not None else policy

# Line 2274+: DiffResult gets correct verdict but wrong policy
return DiffResult(
    verdict=verdict,            # ✓ Correct (API_BREAK with overrides)
    policy=effective_policy,    # ✗ Only base policy name ("strict_abi")
)
```

The reporter at `reporter.py:619-623` then categorizes changes using
`_policy_kind_sets(result.policy)`, which returns the **base policy's** kind
sets, not the overrides. So `func_removed` stays in the "breaking" bucket.

Similarly, `DiffResult.breaking` property at `checker.py:132-153` uses
`_policy_kind_sets(self.policy)` — same issue.

---

## Bug 5: Unhandled Exception When Output Directory Doesn't Exist (MEDIUM)

**Command:**
```bash
abicheck compare v1/libtest.so v2/libtest.so \
  --old-header v1/libtest.h --new-header v2/libtest.h \
  -o /nonexistent/dir/report.md
```

**Problem:** Raw Python traceback instead of user-friendly error:
```
FileNotFoundError: [Errno 2] No such file or directory: '/nonexistent/dir/report.md'
```

**Root Cause:** `cli.py:1103` — `output.write_text()` is called without checking
directory existence. This affects multiple commands:
- `compare`: line 1103
- `compare-release`: line 1486
- `deps`: line 1576
- `stack-check`: line 1640

Notably, `compare-release` with `--output-dir` (line 1374-1375) DOES have the
protection: `output_dir.mkdir(parents=True, exist_ok=True)`. Only the `-o`/
`--output` path lacks it.

---

## ~~Bug 6: `compare-release` Treats Object Files (.o) as Libraries~~ — RECLASSIFIED

**Original claim:** compare-release picks up `.o` object files.

**Code review finding:** This is **not a bug**. The `discover_shared_libraries()`
function in `package.py:579-596` specifically checks for ELF `ET_DYN` (shared
objects, `e_type == 3`). Object files have `e_type == ET_REL (1)` and are
correctly filtered out.

The `.o` file in our test appeared under "Removed Libraries" because it existed
only in the `v1/` directory (created as a build artifact) with no counterpart
in `v2/`. The fallback library matching logic (`_collect_release_inputs`) uses
`_is_supported_compare_input()` which may accept files by extension sniffing.
However, the primary path correctly filters by ELF type.

**Severity downgraded to:** Not a bug (test environment artifact).

---

## Bug 7: `deps` Silently Reports PASS for Non-ELF Files (MEDIUM)

**Command:**
```bash
abicheck deps /usr/bin/which  # this is a shell script
```

**Problem:** WARNING is emitted but verdict is still `Loadability: PASS`,
`ABI risk: PASS`, `Risk score: low`.

**Root Cause:** `resolver.py:267` and `elf_metadata.py:162-166` — When
`parse_elf_metadata()` fails on a non-ELF file, it logs a warning and returns
an **empty** `ElfMetadata()` object (empty `needed` list, empty `soname`):

```python
except (ELFError, OSError, ValueError) as exc:
    log.warning("parse_elf_metadata: failed to open/parse %s: %s", so_path, exc)
    return ElfMetadata()  # empty, no deps
```

Back in `stack_checker.py:186-233`, the check logic is:
```python
graph = resolve_dependencies(binary, ...)
if not graph.nodes:          # False — root node exists
    loadability = FAIL
elif graph.unresolved:       # False — nothing to resolve
    loadability = FAIL
```

Since the root binary gets added as a node (resolver.py:276-285) with an empty
dependency list, the graph has 1 node, no unresolved deps, no missing bindings
→ PASS. There is no validation that the input is actually an ELF binary.

---

## Bug 8: `affected_pct` Always Reports 0.0 in JSON Output (MEDIUM)

**Command:**
```bash
abicheck compare v1/libtest.so v2/libtest.so \
  --old-header v1/libtest.h --new-header v2/libtest.h --format json
```

**Problem:** `affected_pct` is always `0.0` in JSON output regardless of how many
symbols are affected.

**Root Cause:** `report_summary.py:71` — `build_summary()` calls
`compatibility_metrics(result.changes)` **without passing `old_symbol_count`**:

```python
# Line 71:
metrics = compatibility_metrics(result.changes)  # no old_symbol_count!
```

In `compatibility_metrics()` at line 44-67:
```python
if old_symbol_count and old_symbol_count > 0:
    affected_pct = breaking_count / old_symbol_count * 100
else:
    affected_pct = 0.0  # always this path since old_symbol_count is None
```

The `old_symbol_count` parameter is available from the DiffResult (which knows
how many symbols the old library had), but `build_summary()` never extracts or
passes it.

---

## Additional Observations (Not Bugs, But Noteworthy)

### C++ Name Mangling Masks Parameter Changes

When comparing C++ libraries (default `--lang c++`), `multiply(int, int)` →
`multiply(long, long)` is reported as `func_removed` + `func_added` (two
separate mangled symbols `_Z8multiplyii` and `_Z8multiplyll`) rather than
`func_params_changed`. This is technically correct by mangled name, but masks the
real semantic change. In `--lang c` mode, the same change is correctly detected
as `func_params_changed`.

### `-H` (Shared Header) Can Produce Wrong Results

Using `-H` applies the same header to both sides. If the API changed, one side
gets the wrong header, leading to incorrect analysis (e.g., `subtract` reported
as "visibility changed to hidden" instead of "removed").

---

## Test Environment Setup

All tests used hand-compiled shared libraries with DWARF debug info:

```bash
gcc -shared -fPIC -g -o v1/libtest.so v1/libtest.c
gcc -shared -fPIC -g -o v2/libtest.so v2/libtest.c
```

**Tools:** Python 3.11, castxml 0.6.3, GCC 13.3.0, pyelftools 0.32

**Total tests run:** 54
**Confirmed bugs:** 7 (1 reclassified after code review)
**Tests passing correctly:** 47
