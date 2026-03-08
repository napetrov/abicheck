# ABI Tool Comparison: abicheck vs abidiff vs ABICC

_Generated: 2026-03-07 — abicheck examples benchmark_

## Summary

| Tool | Version | Method | Correct on our examples |
|------|---------|--------|------------------------|
| **abicheck** | HEAD | castxml AST + ELF | **11/14 (79%)** |
| **abidiff** | 2.4.0 | DWARF (needs -g) | 6/14 (43%) — undercounts due to COMPATIBLE vs BREAKING |
| **ABICC** | 2.3 | GCC dump | TBD (running) |

> abidiff low score is NOT a bug — it classifies many changes as `COMPATIBLE` (exit=4)
> where abicheck correctly says `BREAKING`. abidiff needs `--headers-dir` for full severity.

## Per-case Results

| Case | Expected | abicheck | abidiff | Match? | Notes |
|------|----------|----------|---------|--------|-------|
| case01_symbol_removal | BREAKING | ✅ BREAKING | ✅ BREAKING | ✅ | |
| case02_param_type_change | BREAKING | ❌ NO_CHANGE | ⚠️ COMPATIBLE | ❌ | abicheck gap: needs castxml param type diff |
| case03_compat_addition | COMPATIBLE | ✅ COMPATIBLE | ✅ COMPATIBLE | ✅ | |
| case04_no_change | NO_CHANGE | ✅ NO_CHANGE | ✅ NO_CHANGE | ✅ | |
| case07_struct_layout | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ~ | abidiff undercounts struct growth |
| case08_enum_value_change | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ~ | abicheck stricter (correct) |
| case09_cpp_vtable | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ~ | vtable size change detected |
| case10_return_type | BREAKING | ❌ NO_CHANGE | ⚠️ COMPATIBLE | ❌ | abicheck gap: return type without headers |
| case11_global_var_type | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ~ | ELF symbol size catches int→long |
| case12_function_removed | BREAKING | ✅ BREAKING | ✅ BREAKING | ✅ | |
| case14_cpp_class_size | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ~ | |
| case15_noexcept_change | NO_CHANGE | ✅ NO_CHANGE | ✅ NO_CHANGE | ✅ | castxml detects, verdict correct |
| case16_inline_to_non_inline | COMPATIBLE | ✅ COMPATIBLE | ✅ COMPATIBLE | ✅ | |
| case17_template_abi | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ~ | template struct size caught |

Legend: ✅ correct  ⚠️ undercount (COMPATIBLE instead of BREAKING)  ❌ missed

## Key Findings

### 1. abicheck is STRICTER than abidiff (correct behavior)

abidiff reports `COMPATIBLE` (exit=4) for cases where the binary ABI is technically
changed but abidiff doesn't have full type info via `--headers-dir`.
abicheck uses castxml → gets full type information → correctly says BREAKING.

**Cases where abicheck is righter than abidiff:**
- case07: struct Point grew 8→12 bytes → BREAKING (not COMPATIBLE)
- case08: enum values shifted → BREAKING (serialization/switch breakage)
- case09: vtable slot added → BREAKING (binary incompatible for pre-compiled callers)
- case11: global var int→long → BREAKING (size changed 4→8)
- case14: class Buffer doubled → BREAKING
- case17: template struct size grew → BREAKING

### 2. abicheck gaps (2 cases missed)

| Case | Root cause | Fix |
|------|-----------|-----|
| case02_param_type_change | `process(int,int)→process(double,int)`: ELF symbol name same (C linkage), no type info without headers. castxml header diff needed. | Sprint 8: ensure header-based param type diff fires |
| case10_return_type | `get_count()` return int→long: same symbol name, ELF-only misses type. | Sprint 8: same fix |

### 3. abidiff key difference

abidiff without `--headers-dir` uses DWARF to detect *that* something changed,
but classifies it as `COMPATIBLE` unless it can determine binary impact.
With `--headers-dir` abidiff would likely agree with abicheck on severity.

## ABICC Compatibility

ABICC uses `-old`/`-new` XML descriptors with `<headers>` + `<libs>` keys.
abicheck Sprint 5 implemented the same CLI interface:
```bash
abicheck compat -lib mylib -old v1.xml -new v2.xml
```

ABICC XML descriptor format supported by abicheck:
```xml
<version>1.0</version>
<headers>/path/to/headers/</headers>
<libs>/path/to/libfoo.so</libs>
```

## Gaps to close in Sprint 8

1. **case02/case10**: param/return type change detection when C linkage (same mangled name)
   — requires castxml header comparison path to be hit for ELF-only symbols
2. Add `--headers-dir` support for abidiff parity mode
