# v2 Coverage Plan — Beyond Sprint 1

Source: "Beyond v1: Practical C/C++ API & ABI Break Mechanisms"

## Evidence Tiers (Detection Priority)

### Tier 1 — ELF-only (no debug info needed, implement first)
| Case | Signal | ChangeKind |
|---|---|---|
| case28_symbol_version_requirement_drift | `.gnu.version_r` / `.gnu.version_d` diff | `SYMBOL_VERSION_REQUIREMENT_ADDED` |
| case29_runpath_rpath_change | `DT_RPATH` vs `DT_RUNPATH` drift | `RPATH_CHANGED` |
| case30_ifunc_introduction | `STT_GNU_IFUNC` type change | `IFUNC_INTRODUCED` |
| case31_soname_or_needed_drift | `DT_SONAME` / `DT_NEEDED` set diff | already partial in v1 |
| case32_common_symbol_resolution_risk | `STT_COMMON` in exported vars | `COMMON_SYMBOL_RISK` |
| — | Symbol binding `GLOBAL→WEAK` or reverse | `SYMBOL_BINDING_CHANGED` |
| — | Symbol type `FUNC→OBJECT` or reverse | `SYMBOL_TYPE_CHANGED` |
| — | `STT_TLS` introduction | `TLS_SYMBOL_ADDED` |

### Tier 2 — DWARF/CTF required
| Case | Signal | ChangeKind |
|---|---|---|
| case19_struct_return_convention | Aggregate return ABI via DWARF + flag | `STRUCT_RETURN_ABI_CHANGED` |
| case20_short_enums | `DW_AT_byte_size` on enum type | `ENUM_UNDERLYING_SIZE_CHANGED` |
| case21_pack_struct_global | Member offsets drift (packing) | `STRUCT_PACKING_CHANGED` |
| case22_calling_convention_attribute | DW_AT_calling_convention | `CALLING_CONVENTION_CHANGED` |
| case23_pragma_pack_drift | DWARF offsets + header AST | `PRAGMA_PACK_DRIFT` |
| case25_type_visibility_exception_boundary | typeinfo/vtable symbol visibility | `TYPE_VISIBILITY_CHANGED` |
| case26_noexcept_mangling | Mangled name encoding (`Do`) diff | extended `FUNC_NOEXCEPT_*` |
| — | `DW_AT_producer` flag drift | `TOOLCHAIN_FLAG_DRIFT` (warning) |

### Tier 3 — Header/AST
| Case | Signal |
|---|---|
| Language linkage change (`extern "C"` removal) | mangling shift detectable in Tier 1 |
| Macro contract changes | requires header AST diff |
| Inline/template body changes | source-level only |

### Tier 4 — Build metadata
| Signal | How |
|---|---|
| `-fshort-enums`, `-fpack-struct`, `-fno-common` | `DW_AT_producer` parsing |
| `-mabi` / `-mabi=*` | `DW_AT_producer` |
| Toolchain major version shift | `DW_AT_producer` |
| `-Wpsabi` affected patterns | correlate with DWARF layout drift |

## Key Design Principles (from doc)

1. **Evidence levels in output** — every change should report what evidence tier detected it
   and confidence level (e.g., "detected via ELF-only — type mismatch undetectable without DWARF").

2. **Without DWARF → ELF-only mode** — explicitly document fallback and what's missed.

3. **Debug companion inputs** — tool should accept `--debug-info path/to/lib.so.debug`
   (split debug packages in distros).

4. **ODR assumption flag** — `--no-odr` to disable same-name-means-same-type optimization.

5. **`ENUM_MEMBER_ADDED` is NOT always BREAKING** — "open" enums (extensible APIs) vs
   "closed" enums (switch-exhaustive consumers). Implement heuristic:
   - If added value exceeds `max(old_values)` AND no overflow → `POTENTIALLY_BREAKING`
   - If added value would change existing switch behavior → `BREAKING`

## Sprint 2 Scope (Proposed)
Priority: Tier 1 ELF-only signals (no new dependencies, pure readelf parsing)

1. `_diff_elf_dynamic`: `DT_NEEDED` set, `DT_SONAME`, `DT_RPATH`/`DT_RUNPATH`
2. `_diff_symbol_versions`: `.gnu.version_r` requirements drift (GLIBC_X not found)
3. `_diff_symbol_metadata`: binding (GLOBAL/WEAK), type (FUNC/OBJECT/TLS/IFUNC), size
4. `_diff_toolchain_flags`: `DW_AT_producer` extraction + ABI-affecting flag detection

## Sprint 3 Scope (Proposed)
DWARF-aware:
1. `ENUM_UNDERLYING_SIZE_CHANGED` (DW_AT_byte_size)
2. `STRUCT_PACKING_CHANGED` (DWARF offsets cross-check with castxml)
3. `TYPE_VISIBILITY_CHANGED` (typeinfo/vtable visibility from ELF + DWARF)
4. `CALLING_CONVENTION_CHANGED` (DW_AT_calling_convention)

## What Cannot Be Detected (explicit limits)
- Semantic/behavioral contract changes (enum value meanings, error code semantics)
- Inline/template body changes for existing binaries
- `_GLIBCXX_USE_CXX11_ABI` dual ABI disagreements (requires build system analysis)
- `LD_DYNAMIC_WEAK` / weak symbol resolution quirks (runtime-only)
