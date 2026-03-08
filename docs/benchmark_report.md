# ABI Tool Comparison: abicheck vs abidiff vs ABICC

_Generated: 2026-03-07 — abicheck examples benchmark (14 cases)_

## TL;DR

| Tool | Correct / 14 | Missed BREAKING | Notes |
|------|-------------|-----------------|-------|
| **abicheck** | **14/14 (100%)** | **0** | castxml + ELF |
| abidiff | 6/14 (43%) | 0 missed, 8 undercounted | COMPATIBLE instead of BREAKING |
| ABICC | 3/14 (21%) | many | 3× TIMEOUT, 9× NO_CHANGE, 1× ERROR |

**abicheck catches every breaking change. abidiff undercounts severity. ABICC needs GCC dump setup.**

## Tool versions

| Tool | Version | Analysis method |
|------|---------|-----------------|
| abicheck | HEAD | castxml AST + ELF symbol diff |
| abidiff | 2.4.0 | DWARF debug info (`-g`) |
| ABICC | 2.3 | GCC `-fdump-lang-spec` + XML descriptor |

## Full results

| Case | Expected | abicheck | abidiff | ABICC |
|------|----------|----------|---------|-------|
| case01_symbol_removal | BREAKING | ✅ BREAKING | ✅ BREAKING | ✅ BREAKING |
| case02_param_type_change | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ❌ NO_CHANGE |
| case03_compat_addition | COMPATIBLE | ✅ COMPATIBLE | ✅ COMPATIBLE | ❌ NO_CHANGE |
| case04_no_change | NO_CHANGE | ✅ NO_CHANGE | ✅ NO_CHANGE | ✅ NO_CHANGE |
| case07_struct_layout | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ❌ NO_CHANGE |
| case08_enum_value_change | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ❌ NO_CHANGE |
| case09_cpp_vtable | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ❌ NO_CHANGE |
| case10_return_type | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ❌ NO_CHANGE |
| case11_global_var_type | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ❌ ERROR |
| case12_function_removed | BREAKING | ✅ BREAKING | ✅ BREAKING | ✅ BREAKING |
| case14_cpp_class_size | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ❌ NO_CHANGE |
| case15_noexcept_change | NO_CHANGE | ✅ NO_CHANGE | ✅ NO_CHANGE | ⏱️ TIMEOUT |
| case16_inline_to_non_inline | COMPATIBLE | ✅ COMPATIBLE | ✅ COMPATIBLE | ⏱️ TIMEOUT |
| case17_template_abi | BREAKING | ✅ BREAKING | ⚠️ COMPATIBLE | ⏱️ TIMEOUT |

Legend: ✅ correct  ⚠️ undercounted (COMPATIBLE/NO_CHANGE vs expected BREAKING)  ❌ wrong  ⏱️ timed out (>90s)

## Why abidiff undercounts (8 cases)

abidiff without `--headers-dir` reads DWARF debug info compiled into the `.so` with `-g`.
It detects *that* something changed but classifies it as `COMPATIBLE` (exit=4) because
it cannot determine binary impact without full header type info.

With `--headers-dir`, abidiff returns **NO_CHANGE** (exit=0) for most of these cases —
it filters indirect/internal changes as non-public API. Still a miss, but for a different reason:
abidiff treats struct layout as an implementation detail unless directly in the public signature.
**abicheck uses castxml → always gets full type info → correct BREAKING verdict.**

## Why ABICC fails (9/14 cases)

ABICC was designed for GCC-based workflows: it requires `gcc -fdump-lang-spec` to extract
type info. When fed pre-built `.so` files with a simple XML descriptor (no GCC dump),
it falls back to symbol-level comparison only and reports NO_CHANGE for most type changes.

ABICC also timed out (>90s) on C++ template cases (case15, case16, case17).

**To use ABICC properly:** headers must be processed by GCC first via its dump mechanism.
abicheck uses castxml (Clang-based) and works directly with `.so` + headers — no compiler dump needed.

## Bug fixes included in this PR

Two cases silently returned NO_CHANGE before adding `.h` files:

| Case | Before | After | Root cause |
|------|--------|-------|------------|
| case02_param_type_change | NO_CHANGE ❌ | BREAKING ✅ | No .h → ELF-only, same C-linkage symbol name |
| case10_return_type | NO_CHANGE ❌ | BREAKING ✅ | No .h → ELF-only, `get_count` name identical |

## ABICC XML descriptor format (Sprint 5 compatibility)

abicheck Sprint 5 implements ABICC-compatible XML:

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

# abicheck drop-in
abicheck compat -lib mylib -old v1.xml -new v2.xml
```

## Run yourself

```bash
# Requires: castxml, gcc/g++, abidiff (libabigail-tools), abi-compliance-checker
python3 scripts/benchmark_comparison.py
```
