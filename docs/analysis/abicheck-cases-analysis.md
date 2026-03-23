# Comprehensive Analysis of abicheck Example Cases

> Generated analysis of all 62 example cases in the abicheck repository,
> covering verdict classification, detection mechanisms, platform coverage,
> and architectural patterns.

## 1. Case Inventory by Verdict Category

### BREAKING (36 cases)
Binary ABI incompatibilities — old binaries will crash or malfunction.

| Case | Scenario | ChangeKind(s) | Platforms | ABI Break | API Break |
|------|----------|---------------|-----------|-----------|-----------|
| 01 | Symbol removal | `func_removed` | linux, macos, windows | Yes | Yes |
| 02 | Parameter type change | `func_params_changed` | linux | Yes | Yes |
| 06 | Visibility change (default→hidden) | `func_visibility_changed` | linux | Yes | No |
| 07 | Struct layout (field added) | `type_size_changed` | linux | Yes | Yes |
| 08 | Enum value change | `enum_member_value_changed` | linux | Yes | Yes |
| 09 | C++ vtable reorder | `type_vtable_changed` | linux | Yes | Yes |
| 10 | Return type change | `func_return_changed` | linux | Yes | Yes |
| 11 | Global variable type change | `var_type_changed` | linux | Yes | Yes |
| 12 | Function removed | `func_removed` | linux, macos, windows | Yes | Yes |
| 14 | C++ class size (private member) | `type_size_changed` | linux | Yes | Yes |
| 17 | Template ABI size change | `type_size_changed` | linux | Yes | Yes |
| 18 | Dependency leak (transitive type) | `type_size_changed` | linux | Yes | No |
| 19 | Enum member removed | `enum_member_removed` | linux, macos, windows | Yes | Yes |
| 20 | Enum member value changed | `enum_member_value_changed` | linux, macos, windows | Yes | Yes |
| 21 | Method became static | `func_static_changed` | linux | Yes | Yes |
| 22 | Method const changed | `func_cv_changed` | linux, macos, windows | Yes | Yes |
| 23 | Pure virtual added | `func_pure_virtual_added` | linux, macos, windows | Yes | Yes |
| 24 | Union field removed | `union_field_removed` | linux, macos, windows | Yes | Yes |
| 26 | Union field added (size grows) | `type_size_changed` | linux, macos, windows | Yes | No |
| 28 | Typedef became opaque | `type_became_opaque` | linux, macos, windows | Yes | Yes |
| 30 | Field qualifiers changed | varies | linux, macos, windows | Yes | Yes |
| 33 | Pointer level change | `param_pointer_level_changed` | linux, macos, windows | Yes | Yes |
| 35 | Field renamed | `field_renamed` | linux, macos, windows | No | Yes |
| 36 | Anonymous struct changed | `anon_field_changed` | linux, macos, windows | Yes | Yes |
| 37 | Base class changed | `type_base_changed` | linux, macos, windows | Yes | Yes |
| 38 | Virtual methods changed | `type_vtable_changed` | linux, macos, windows | Yes | Yes |
| 39 | Variable became const | `var_became_const` | linux, macos, windows | Yes | Yes |
| 40 | Field layout changed | `type_field_offset_changed` | linux, macos, windows | Yes | Yes |
| 41 | Type changes (multi) | varies | linux, macos | Yes | Yes |
| 42 | Type alignment changed | `type_alignment_changed` | linux, macos | Yes | Yes |
| 43 | Base class member added | `type_size_changed` | linux, macos, windows | Yes | Yes |
| 44 | Cyclic type member added | `type_size_changed` | linux, macos, windows | Yes | Yes |
| 45 | Multi-dim array change | `type_size_changed` | linux, macos, windows | Yes | Yes |
| 46 | Pointer chain type change | `func_return_changed` | linux, macos, windows | Yes | Yes |
| 48 | Leaf struct through pointer | `type_size_changed` | linux, macos, windows | Yes | Yes |
| 53 | Namespace pollution | varies | linux | Yes | Yes |
| 55 | Type kind changed (struct→union) | `type_kind_changed` | linux, macos | Yes | Yes |
| 56 | Struct packing changed | `struct_packing_changed` | linux, macos | Yes | Yes |
| 57 | Enum underlying size changed | `enum_underlying_size_changed` | linux, macos | Yes | Yes |
| 58 | Variable removed | `var_removed` | linux, macos | Yes | Yes |
| 59 | Function became inline | `func_removed` | linux, macos | Yes | No |
| 60 | Base class position changed | `base_class_position_changed` | linux, macos | Yes | Yes |

### API_BREAK (2 cases)
Source-level breaks — recompilation required, but binary ABI preserved.

| Case | Scenario | ChangeKind(s) | Platforms |
|------|----------|---------------|-----------|
| 31 | Enum member renamed | `enum_member_renamed` | linux, macos, windows |
| 34 | Access level changed | `method_access_changed` / `field_access_changed` | linux, macos |

### COMPATIBLE_WITH_RISK (1 case)
Binary-compatible but deployment risk present.

| Case | Scenario | ChangeKind(s) | Platforms |
|------|----------|---------------|-----------|
| 15 | noexcept removed | `func_noexcept_removed` + `symbol_version_required_added` | linux |

### COMPATIBLE (15 cases)
Safe changes — existing binaries unaffected.

| Case | Scenario | ChangeKind(s) | Category | Bad Practice |
|------|----------|---------------|----------|--------------|
| 03 | Compatible addition | `func_added` | addition | No |
| 05 | SONAME missing | `soname_missing` | quality | Yes |
| 13 | Symbol versioning | — | quality | No |
| 16 | Inline to non-inline | `func_added` | addition | No |
| 25 | Enum member added | `enum_member_added` | addition | No |
| 26b | Union field added (size same) | — | addition | No |
| 27 | Symbol binding weakened | `symbol_binding_changed` | quality | No |
| 29 | IFUNC transition | `ifunc_introduced` | quality | No |
| 47 | Inline to outlined | `func_added` | addition | No |
| 49 | Executable stack | `executable_stack` | quality | Yes |
| 50 | SONAME inconsistent | `soname_missing` | quality | Yes |
| 51 | Protected visibility | `func_visibility_protected_changed` | quality | No |
| 52 | RPATH leak | `rpath_changed` | quality | Yes |
| 54 | Used reserved field | `used_reserved_field` | quality | No |
| 61 | Variable added | `var_added` | addition | No |
| 62 | Type field added compatible | `type_field_added_compatible` | addition | No |

### NO_CHANGE (2 cases)
Libraries are identical or changes are invisible.

| Case | Scenario | Platforms |
|------|----------|-----------|
| 04 | No change (identical) | linux, macos, windows |
| 32 | Parameter defaults (compile-time only) | linux, macos, windows |

---

## 2. Detection Architecture Analysis

### 2.1 Change Detection Pipeline

```
Binary (ELF/PE/Mach-O) → Symbol Extraction → diff_symbols.py
                        → DWARF/BTF/CTF   → dwarf_snapshot.py → diff_types.py
Headers (.h/.hpp)       → castxml AST      → dumper.py        → diff_types.py
                                                               → diff_platform.py
                                                                     ↓
                                                              checker_policy.py
                                                                     ↓
                                                              Verdict (5-tier)
```

### 2.2 Verdict Computation Logic

The verdict is determined by the **highest severity** change kind detected:

1. **BREAKING** — Any `BREAKING_KINDS` match → exit code 4
2. **API_BREAK** — Any `API_BREAK_KINDS` match → exit code 2
3. **COMPATIBLE_WITH_RISK** — Any `RISK_KINDS` match → exit code 0
4. **COMPATIBLE** — Any `COMPATIBLE_KINDS` match → exit code 0
5. **NO_CHANGE** — No changes detected → exit code 0

### 2.3 Change Kind Count by Default Verdict

| Default Verdict | Count | Examples |
|----------------|-------|---------|
| BREAKING | 52 | `func_removed`, `type_size_changed`, `var_type_changed`, ... |
| API_BREAK | 13 | `enum_member_renamed`, `field_renamed`, `method_access_changed`, ... |
| COMPATIBLE_WITH_RISK | 5 | `enum_last_member_value_changed`, `symbol_version_required_added`, ... |
| COMPATIBLE | 58 | `func_added`, `soname_changed`, `executable_stack`, ... |

### 2.4 Policy Override Matrix

Three built-in policies allow verdict downgrades:

| Policy | Purpose | Notable Overrides |
|--------|---------|-------------------|
| `strict_abi` | System libraries (default) | No overrides — strictest |
| `sdk_vendor` | Vendor SDKs | `enum_member_renamed` → COMPATIBLE, `field_renamed` → COMPATIBLE, access changes → COMPATIBLE |
| `plugin_abi` | Plugins rebuilt with host | `calling_convention_changed` → COMPATIBLE, `frame_register_changed` → COMPATIBLE |

---

## 3. Platform Coverage Analysis

### 3.1 Cross-Platform Support Matrix

| Platform | Full Cases | Limited Cases | Known Gaps |
|----------|-----------|---------------|------------|
| **Linux** | 62 (all) | — | — |
| **macOS** | 42 | 6 with known gaps | Types invisible without castxml |
| **Windows** | 24 | — | Fewer cases target PE/COFF |

### 3.2 Known Platform Gaps (from ground_truth.json)

| Case | Platform | Gap Description |
|------|----------|----------------|
| 42 (type alignment) | macOS | Returns NO_CHANGE — Mach-O captures only symbols, not type alignment |
| 54 (reserved field) | macOS | Returns NO_CHANGE — struct field renames invisible without castxml |
| 55 (type kind) | macOS | Returns NO_CHANGE — struct→union change invisible without castxml |
| 56 (packing) | macOS | Returns NO_CHANGE — packing/layout changes invisible without castxml |
| 57 (enum size) | macOS | Returns NO_CHANGE — enum underlying size invisible without castxml |
| 58 (var removed) | macOS | Returns COMPATIBLE — Mach-O export table doesn't distinguish func/var |
| 60 (base class pos) | macOS | Returns NO_CHANGE — base class layout invisible without headers |

**Root cause:** macOS Mach-O analysis without castxml can only see exported symbol names. Type-level changes (layout, alignment, packing) require either DWARF debug info or castxml header analysis.

---

## 4. Case Categories by ABI Change Pattern

### 4.1 Symbol-Level Changes (detected via .dynsym / export table)

These are the most reliably detected across platforms:

| Pattern | Cases | Detection Layer |
|---------|-------|----------------|
| Symbol removal | 01, 12, 58, 59 | `diff_symbols.py` |
| Symbol addition | 03, 16, 25, 47, 61 | `diff_symbols.py` |
| Visibility change | 06, 51 | `diff_symbols.py` + `elf_metadata.py` |
| Binding change | 27 | `diff_symbols.py` |
| IFUNC transition | 29 | `diff_symbols.py` |
| Symbol versioning | 13 | `diff_symbols.py` |

### 4.2 Type/Layout Changes (detected via castxml AST or DWARF)

Require header analysis or debug info:

| Pattern | Cases | Detection Layer |
|---------|-------|----------------|
| Struct size change | 07, 14, 17, 43, 44, 45, 48 | `diff_types.py` |
| Field offset shift | 40 | `diff_types.py` |
| Alignment change | 42 | `diff_types.py` + `dwarf_advanced.py` |
| Packing change | 56 | `dwarf_advanced.py` |
| Type kind change | 55 | `diff_types.py` |
| Opaque transition | 28 | `diff_types.py` |

### 4.3 C++ ABI Changes

Specific to C++ name mangling and vtable layout:

| Pattern | Cases | Detection Layer |
|---------|-------|----------------|
| Vtable reorder | 09, 38 | `diff_types.py` |
| Method qualification | 21, 22 | `diff_types.py` |
| Pure virtual added | 23 | `diff_types.py` |
| Base class change | 37, 60 | `diff_types.py` |
| Template ABI | 17 | `diff_types.py` |
| noexcept change | 15 | `diff_types.py` + `diff_symbols.py` |

### 4.4 Enum Changes

| Pattern | Cases | Detection Layer |
|---------|-------|----------------|
| Value changed | 08, 20 | `diff_types.py` |
| Member removed | 19 | `diff_types.py` |
| Member added | 25 | `diff_types.py` |
| Member renamed | 31 | `diff_types.py` |
| Underlying size | 57 | `dwarf_metadata.py` |

### 4.5 ELF Metadata / Quality Issues

Non-ABI-breaking but reportable:

| Pattern | Cases | Detection Layer |
|---------|-------|----------------|
| SONAME | 05, 50 | `diff_platform.py` |
| Executable stack | 49 | `diff_platform.py` |
| RPATH leak | 52 | `diff_platform.py` |
| Namespace pollution | 53 | `diff_platform.py` |
| Reserved field usage | 54 | `diff_types.py` |
| Protected visibility | 51 | `diff_symbols.py` |

---

## 5. Interesting Case Patterns

### 5.1 Case Pairs (contrasting verdicts for similar changes)

| Cases | Pattern | Key Difference |
|-------|---------|----------------|
| 26 vs 26b | Union field added | 26: size grows (BREAKING), 26b: size unchanged (COMPATIBLE) |
| 16 vs 59 | Inline ↔ outlined | 16: inline→non-inline adds symbol (COMPATIBLE), 59: non-inline→inline removes symbol (BREAKING) |
| 01 vs 03 | Symbol removal vs addition | 01: removal (BREAKING), 03: addition (COMPATIBLE) |
| 07 vs 62 | Field added to struct | 07: public struct grows (BREAKING), 62: opaque struct (COMPATIBLE) |
| 47 vs 59 | Outlined ↔ inline | 47: inline→outlined (COMPATIBLE), 59: outlined→inline (BREAKING) |

### 5.2 Multi-ChangeKind Cases

Some cases trigger multiple change kinds simultaneously:

| Case | Primary Kind | Secondary Kind(s) | Verdict Driver |
|------|-------------|-------------------|----------------|
| 15 | `func_noexcept_removed` (COMPATIBLE) | `symbol_version_required_added` (RISK) | RISK upgrades final verdict |
| 18 | `type_size_changed` (BREAKING) | Transitive dependency detection | BREAKING from leaked type |
| 53 | `visibility_leak` (COMPATIBLE) | `func_removed` (BREAKING) | BREAKING from removed symbols |

### 5.3 Cases Testing Boundaries

| Case | What It Tests | Why Important |
|------|--------------|---------------|
| 04 | Identical libraries | Ensures no false positives |
| 26b | Safe union addition | Proves size-aware union analysis |
| 32 | Default parameter change | Proves compile-time-only changes are invisible to ABI |
| 54 | Reserved field activation | Validates struct evolution pattern detection |
| 62 | Opaque struct field add | Proves pointer-only usage prevents break |

---

## 6. Test Coverage Cross-Reference

### 6.1 Test Files Covering Example Cases

| Test File | Coverage | Notes |
|-----------|----------|-------|
| `test_abi_examples.py` | Cases 01-18 | Legacy, hardcoded, Linux-only |
| `test_example_autodiscovery.py` | All 62 cases | Auto-discovers from ground_truth.json |
| `test_changekind_completeness.py` | All 128 ChangeKinds | Ensures registry ↔ enum sync |
| `test_new_detectors.py` | New gap detectors | Sprint-specific detector tests |

### 6.2 Ground Truth Validation Properties

For each case, `ground_truth.json` tracks:
- `expected` — Verdict string
- `category` — Classification bucket (breaking/api_break/risk/addition/quality/no_change)
- `platforms` — Supported platform list
- `abi_break` — Boolean: binary incompatibility?
- `api_break` — Boolean: source incompatibility?
- `bad_practice` — Boolean: packaging/security concern?
- `expected_kinds` — ChangeKind values that MUST appear (subset check)
- `expected_absent_kinds` — ChangeKind values that MUST NOT appear (false positive guard)
- `known_gap` — Platform-specific xfail reason
- `description` — Human-readable scenario explanation

---

## 7. Architectural Observations

### 7.1 Strengths

1. **Single source of truth** — `change_registry.py` contains all ChangeKind metadata in one place; classification sets derive automatically.

2. **No shotgun surgery** — Adding a new ChangeKind requires one `_E(...)` entry in the registry. The BREAKING/COMPATIBLE/API_BREAK sets, impact text, and policy overrides all derive from it.

3. **Ground truth separation** — `ground_truth.json` is the single authority for expected verdicts, decoupled from test logic. Tests auto-discover cases from the filesystem.

4. **128 change kinds** — Far more comprehensive than alternatives (ABICC ~40, libabigail ~50). Covers ELF metadata, DWARF layout, C++ ABI, and quality/security concerns.

5. **Multi-layer detection** — Combines symbol-level, type-level, DWARF-level, and platform-level analysis for defense-in-depth detection.

### 7.2 Known Limitations

1. **macOS type analysis** — Without castxml or DWARF, Mach-O analysis is limited to export table symbols. 7 cases have documented gaps on macOS.

2. **Windows coverage** — Only 24 of 62 cases target Windows. PE/COFF analysis relies on PDB debug info for type-level detection.

3. **DWARF dependency** — Advanced detection (packing, alignment, calling convention) requires `-g` debug info. Stripped binaries fall back to symbol-only analysis.

4. **castxml dependency** — Header-based analysis requires castxml, which itself depends on clang. Not available in all CI environments.

### 7.3 Evolution Path

The case catalog follows a clear progression:
- **Sprint 1** (cases 01-18): Core symbol and type checks
- **Sprint 2** (cases 19-29): Gap detectors, ELF metadata
- **Sprint 3** (cases 30-40): DWARF layout, method qualifiers
- **Sprint 4** (cases 41-50): Advanced DWARF, libabigail parity
- **Sprint 5** (cases 51-57): ELF quality, platform-specific
- **Sprint 6** (cases 58-62): Variable handling, compatible additions

---

## 8. Verdict Decision Tree

```
Does the change kind have default_verdict == BREAKING?
├── Yes → Final verdict: BREAKING (exit 4)
│         Examples: func_removed, type_size_changed, var_type_changed
│
├── No → Does the change kind have default_verdict == API_BREAK?
│   ├── Yes → Final verdict: API_BREAK (exit 2)
│   │         Examples: enum_member_renamed, field_renamed
│   │
│   ├── No → Does the change kind have default_verdict == COMPATIBLE_WITH_RISK?
│   │   ├── Yes → Final verdict: COMPATIBLE_WITH_RISK (exit 0)
│   │   │         Examples: enum_last_member_value_changed, symbol_version_required_added
│   │   │
│   │   └── No → Is the change kind in COMPATIBLE_KINDS?
│   │       ├── Yes → Final verdict: COMPATIBLE (exit 0)
│   │       │         Is it an addition? → Sub-categorize as ADDITION
│   │       │         Otherwise → Sub-categorize as QUALITY
│   │       │
│   │       └── No → Final verdict: NO_CHANGE (exit 0)
│   │
│   └── (Policy overrides can downgrade any verdict)
│       Example: sdk_vendor policy: enum_member_renamed → COMPATIBLE
```

**Important:** When multiple changes are detected, the overall verdict is the **maximum severity** across all individual changes.
