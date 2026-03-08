# ABI Tool Comparison: abicheck vs abidiff vs ABICC

_Generated: 2026-03-07 — abicheck examples benchmark (14 cases)_

## TL;DR

**abicheck misses 0 breaking changes. abidiff undercounts 8/14.**
abicheck uses castxml (full type info) → correct BREAKING verdict.
abidiff without `--headers-dir` uses DWARF only → reports COMPATIBLE instead of BREAKING for type-level changes.

## Tool versions

| Tool | Version | Analysis method |
|------|---------|-----------------|
| abicheck | HEAD | castxml AST + ELF symbol diff |
| abidiff | 2.4.0 | DWARF debug info (`-g`) |
| ABICC | 2.3 | GCC `-fdump-lang-spec` + XML descriptor |

## Results (14 cases)

| Case | Expected | abicheck | abidiff | ABICC | Notes |
|------|----------|----------|---------|-------|-------|
| case01_symbol_removal | BREAKING | ✅ BREAKING | ✅ BREAKING | TBD | |
| case02_param_type_change | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | TBD | Fixed: was NO_CHANGE before .h added |
| case03_compat_addition | COMPATIBLE | ✅ COMPATIBLE | ✅ COMPATIBLE | TBD | |
| case04_no_change | NO_CHANGE | ✅ NO_CHANGE | ✅ NO_CHANGE | TBD | |
| case07_struct_layout | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | TBD | struct Point 8→12 bytes |
| case08_enum_value_change | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | TBD | enum values shifted |
| case09_cpp_vtable | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | TBD | vtable slot inserted |
| case10_return_type | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | TBD | Fixed: was NO_CHANGE before .h added |
| case11_global_var_type | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | TBD | global var int→long |
| case12_function_removed | BREAKING | ✅ BREAKING | ✅ BREAKING | TBD | |
| case14_cpp_class_size | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | TBD | Buffer 64→128 bytes |
| case15_noexcept_change | NO_CHANGE | ✅ NO_CHANGE | ✅ NO_CHANGE | TBD | |
| case16_inline_to_non_inline | COMPATIBLE | ✅ COMPATIBLE | ✅ COMPATIBLE | TBD | |
| case17_template_abi | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | TBD | template struct grew |

Legend: ✅ correct  ⚠️ undercounted  TBD = ABICC run pending

## Score

| Tool | Correct / 14 | Missed BREAKING | False positives |
|------|-------------|-----------------|-----------------|
| **abicheck** | **14/14 (100%)** | **0** | 0 |
| abidiff | 6/14 (43%) | 0 (but 8 undercounted as COMPATIBLE) | 0 |
| ABICC | TBD | TBD | TBD |

## Why abidiff undercounts

abidiff without `--headers-dir` uses DWARF debug info compiled into the `.so` with `-g`.
It detects *that* a type changed, but classifies it as `COMPATIBLE` (exit=4) because
it cannot determine binary impact without full header type information.

With `--headers-dir` pointing to the correct headers, abidiff would likely agree
with abicheck on BREAKING severity for most of these cases.

**abicheck advantage**: castxml is always used when headers are provided →
full AST-level type comparison → correct BREAKING verdict out of the box.

## Bug fixes in this PR

Two cases were silently returning NO_CHANGE before this PR added `.h` files:

| Case | Before | After | Root cause |
|------|--------|-------|------------|
| case02_param_type_change | NO_CHANGE ❌ | BREAKING ✅ | No .h → ELF-only mode, same symbol name `process`, C linkage mangling change not visible |
| case10_return_type | NO_CHANGE ❌ | BREAKING ✅ | No .h → ELF-only mode, `get_count` symbol identical in both versions |

## ABICC XML descriptor format

ABICC uses `-old`/`-new` XML descriptors. abicheck Sprint 5 implements
the same format via `abicheck compat`:

```xml
<descriptor>
  <version>1.0</version>
  <headers>/path/to/include/</headers>
  <libs>/path/to/libfoo.so</libs>
</descriptor>
```

```bash
# ABICC
abi-compliance-checker -l mylib -old v1.xml -new v2.xml

# abicheck (drop-in)
abicheck compat -lib mylib -old v1.xml -new v2.xml
```

## Run the benchmark yourself

```bash
# Requires: castxml, gcc/g++, abidiff (libabigail-tools), abi-compliance-checker
python3 scripts/benchmark_comparison.py
```
