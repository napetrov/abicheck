# Abicheck Performance and Memory Consumption Analysis

## Executive Summary

This analysis identifies **7 performance gaps** and **4 memory consumption concerns** in abicheck's scan pipeline. The most impactful issues are in the post-processing/enrichment phase of `checker.py`, where O(n*m) algorithms and repeated regex compilation create scalability bottlenecks for large C++ libraries (10k+ symbols, 1k+ types).

---

## 1. Performance Gaps

### Gap 1: O(n*m) Complexity in `_enrich_affected_symbols` (HIGH impact)

**File:** `checker.py:2033-2119`

The `_enrich_affected_symbols` function has nested loops that scale poorly:

```python
for _mangled, func in old_pub.items():        # O(F) functions
    for tname in affected_types:               # O(T) types
        if any(tname in ft for ft in func_types_used):  # O(P) params
```

**Complexity:** O(F * T * P) where F = public functions, T = affected types, P = average params per function.

Additionally, the transitive closure computation at line 2096-2108 re-scans ALL public functions for every ancestor type:

```python
for tname in affected_types:           # O(T)
    ancestors = _all_ancestors(tname)  # O(T) BFS
    for parent in ancestors:           # O(A) ancestors
        for _mangled, func in old_pub.items():  # O(F) — full re-scan!
```

**Worst case:** O(T * A * F * P) — for a library with 5000 functions, 200 types, and 50 ancestor chains, this is ~50M string containment checks.

**Fix:** Pre-build a reverse index `type_name -> set[function_mangled]` once upfront, then do O(1) lookups per type. Use `set` for `func_types_used` and check membership instead of substring containment.

---

### Gap 2: Regex Recompilation in `_match_root_type` (HIGH impact)

**File:** `checker.py:2286-2307`

Called once per `(derived_change, root_type)` pair during redundancy filtering:

```python
def _match_root_type(c: Change, root_types: dict[str, Change]) -> str | None:
    for type_name in root_types:
        pattern = r'(?<![A-Za-z0-9_])' + re.escape(type_name) + r'(?![A-Za-z0-9_])'
        if c.old_value and re.search(pattern, c.old_value):
            ...
```

For every derived change, this compiles a new regex for every root type, then searches up to 3 strings (old_value, new_value, description). With 100 root types and 500 derived changes, that's 150,000 regex compilations.

**Fix:** Pre-compile regex patterns for all root types at the start of `_filter_redundant()` and pass the compiled dict to `_match_root_type`.

---

### Gap 3: Regex Recompilation in `_is_pointer_only_type` / `_has_public_pointer_factory` (MEDIUM impact)

**File:** `checker.py:2320-2378`

Both functions compile a regex per type name, then scan ALL public functions:

```python
def _is_pointer_only_type(type_name: str, snap: AbiSnapshot) -> bool:
    bare_re = re.compile(r'\b' + re.escape(type_name) + r'\b')  # compiled per call
    for f in snap.functions:  # full scan
        ...
```

Called from `_filter_opaque_size_changes` for each type with a size change, in both old AND new snapshots. For N types with size changes, this is 2N full function scans with freshly compiled regexes.

**Fix:** Cache compiled regexes or batch-process all types in a single function scan pass.

---

### Gap 4: Duplicate ELF File Opens and Section Iterations (MEDIUM impact)

**File:** `dumper.py:1085-1115`, `elf_metadata.py:200-221`

The dump pipeline opens the same ELF file multiple times:
1. `_pyelftools_exported_symbols()` — opens ELF, iterates `.dynsym` + `.symtab`
2. `parse_elf_metadata()` — opens ELF again, re-iterates `.dynsym` + all sections
3. `parse_dwarf()` (via `dwarf_unified.py`) — opens ELF a third time for DWARF
4. `build_snapshot_from_dwarf()` — opens ELF a fourth time for DWARF CU walking

Each ELF open involves file I/O, magic byte validation, ELF header parsing, and section header table loading. For a 100MB `.so` with large `.debug_info`, this redundant I/O is measurable.

**Fix:** Open the ELF file once and pass the `ELFFile` object through the pipeline. The `_pyelftools_exported_symbols` data is a subset of `parse_elf_metadata` — they could be unified.

---

### Gap 5: `_correlate_symbol_versions` Iterates Sections Twice (LOW impact)

**File:** `elf_metadata.py:487-561`

`_correlate_symbol_versions` iterates ALL ELF sections again to find `.gnu.version` and `.dynsym`, even though the main `_parse()` function already iterated all sections:

```python
# First iteration in _parse() line 200
for section in elf.iter_sections():
    ...

# Second iteration in _correlate_symbol_versions() line 504
for section in elf.iter_sections():
    if isinstance(section, GNUVerSymSection):
        ...
# Third iteration at line 522
for section in elf.iter_sections():
    if isinstance(section, SymbolTableSection) and section.name == ".dynsym":
        ...
```

**Fix:** Capture the `.gnu.version` and `.dynsym` sections during the main section iteration loop and pass them to `_correlate_symbol_versions`.

---

### Gap 6: Sequential Detector Execution (MEDIUM impact)

**File:** `checker.py:3074-3084`

All 30 detectors run sequentially in a single loop:

```python
for spec in detector_fns:
    detected = spec.run(old, new)
    changes.extend(detected)
```

Many detectors are independent and could run in parallel. For example, `_diff_functions`, `_diff_types`, `_diff_enums`, `_diff_elf`, and `_diff_dwarf` all read from different parts of the snapshot and produce independent change lists.

**Fix:** Use `concurrent.futures.ThreadPoolExecutor` for independent detectors. Given Python's GIL, the main benefit would come from I/O-bound detectors (DWARF), but `ProcessPoolExecutor` could parallelize CPU-bound type diffing for very large snapshots.

---

### Gap 7: `_detect_cpp_headers` Reads Entire File Content (LOW impact)

**File:** `dumper.py:254-278`

For C/C++ auto-detection, every header file is read entirely into memory and scanned with 20+ compiled regex patterns line by line:

```python
for p in header_paths:
    content = p.read_bytes()                    # entire file in memory
    content = re.sub(rb"/\*.*?\*/", b"", content, flags=re.DOTALL)  # strip comments
    for line in content.split(b"\n"):           # split into lines
        stripped = line.split(b"//")[0]
        if any(pat.search(stripped) for pat in _CPP_PATTERNS):  # 20+ patterns
```

For large header collections (e.g., Qt or Boost), this scans hundreds of files unnecessarily after the first C++ indicator is found.

**Fix:** Return `True` as soon as the first C++ pattern matches (the code already does this, but it still reads the entire file before scanning). Read files in chunks or limit scanning to the first N lines.

---

## 2. Memory Consumption Concerns

### Concern 1: `dataclasses.asdict()` Deep Copy in Serialization (HIGH impact)

**File:** `serialization.py:62-102`

`snapshot_to_dict()` calls `asdict(snap)` which performs a deep recursive copy of the entire snapshot tree:

```python
def snapshot_to_dict(snap: AbiSnapshot) -> dict[str, Any]:
    d = asdict(snap)  # Deep copy of ALL functions, types, params, fields, ELF symbols...
```

For a large library with 10,000 functions (each with 5 params) and 2,000 types (each with 10 fields), plus ELF metadata with 15,000 symbols, `asdict()` creates ~200,000 new dict objects. This roughly doubles the memory footprint during serialization.

Then `_sets_to_lists()` walks the entire tree again, creating a second copy of all list/dict structures.

**Fix:** Implement a custom serialization method that writes directly to a JSON stream without creating an intermediate dict tree. Or use `__dict__` access with a shallow conversion strategy.

---

### Concern 2: Dual Snapshot Retention During Comparison (MEDIUM impact)

**File:** `checker.py:2997-3178`

During `compare()`, both old and new snapshots must be fully loaded in memory simultaneously. Each snapshot contains:
- `functions: list[Function]` — N function objects
- `types: list[RecordType]` — M type objects with nested field lists
- `elf.symbols: list[ElfSymbol]` — K ELF symbol objects
- `dwarf.structs: dict[str, StructLayout]` — J struct layouts with field lists
- Lazy indexes (`_func_by_mangled`, `_var_by_mangled`, `_type_by_name`) — 3 additional dicts

For a large library (e.g., libstdc++ with ~15K symbols), each snapshot may consume 50-100MB. Two snapshots + their indexes = 200-400MB.

**Fix:** Consider streaming comparison where only relevant subsets of the snapshot are loaded. Or implement a memory-mapped snapshot format that doesn't require full deserialization.

---

### Concern 3: DWARF DIE Tree Expansion via `list(die.iter_children())` (MEDIUM impact)

**Files:** `dwarf_metadata.py:231`, `dwarf_snapshot.py:295`

Both DWARF processing modules materialize all children of every DIE into a list before pushing onto the stack:

```python
for child in reversed(list(die.iter_children())):  # materializes full child list
    stack.append((child, next_scope))
```

For a compilation unit with 100,000 DIEs (common in template-heavy C++ like Boost), this creates a temporary list at every non-leaf node. The peak memory includes all these temporary lists before they're garbage collected.

**Fix:** Iterate children directly without `reversed()` + `list()` — use a LIFO approach that doesn't require reversal, or use `appendleft` with a `deque`.

---

### Concern 4: Unbounded Change Lists Before Dedup (LOW impact)

**File:** `checker.py:3072-3084`

All 30 detectors append to a single `changes` list before any deduplication. For a major library rewrite, this can produce thousands of redundant changes:

```python
changes: list[Change] = []
for spec in detector_fns:
    detected = spec.run(old, new)
    changes.extend(detected)
# Dedup happens AFTER all detectors have run (line 3089+)
```

The dedup passes then create multiple intermediate lists (`stage1`, `stage2`, `result`), tripling the peak memory for the change list.

**Fix:** Apply early dedup between detector groups, or use a set-based structure for exact dedup as changes are added.

---

## 3. Summary Table

| # | Issue | Location | Severity | Type |
|---|-------|----------|----------|------|
| 1 | O(n*m) in `_enrich_affected_symbols` | checker.py:2033 | HIGH | Performance |
| 2 | Regex recompilation in `_match_root_type` | checker.py:2286 | HIGH | Performance |
| 3 | Regex recompilation in opaque-type checks | checker.py:2320 | MEDIUM | Performance |
| 4 | Duplicate ELF file opens (4x) | dumper.py / elf_metadata.py | MEDIUM | Performance |
| 5 | Triple section iteration in version correlation | elf_metadata.py:487 | LOW | Performance |
| 6 | Sequential detector execution | checker.py:3074 | MEDIUM | Performance |
| 7 | Full header content scanning | dumper.py:254 | LOW | Performance |
| 8 | `asdict()` deep copy during serialization | serialization.py:62 | HIGH | Memory |
| 9 | Dual snapshot retention | checker.py:2997 | MEDIUM | Memory |
| 10 | DIE child list materialization | dwarf_metadata.py:231 | MEDIUM | Memory |
| 11 | Unbounded pre-dedup change lists | checker.py:3072 | LOW | Memory |

---

## 4. Recommendations (Priority Order)

1. **Pre-build type-to-function index** in `_enrich_affected_symbols` — eliminates the O(F*T*P) inner loop
2. **Pre-compile regex patterns** in `_filter_redundant` — eliminates 100K+ regex compilations
3. **Unify ELF file opens** — open once, pass `ELFFile` through pipeline
4. **Replace `asdict()` with streaming serialization** — eliminates full deep copy
5. **Avoid `list(die.iter_children())`** in DWARF traversal — reduces transient allocations
6. **Batch opaque-type regex checks** — single function scan for all candidate types
