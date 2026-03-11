# ABI Tool Comparison: abicheck vs abidiff vs ABICC

_Last updated: 2026-03-11 — 42 example cases, onedal-build (Ubuntu, 8 vCPU)_

> **For a detailed explanation of how each tool works, why the numbers are what they are,
> and how to choose the right tool — see [tool_comparison.md](tool_comparison.md).**

## Benchmark scope and methodology

- **42 cases**, all compiled with `-g -O2`, `gcc 13`, `x86_64 Linux` (Ubuntu 22.04)
- All benchmark runs are **sequential** (one case at a time)
- Scoring: a result is correct only if it **exactly matches** the expected verdict in `ground_truth.json`
- `⚠️` in the table means "wrong or undercounted" (e.g. `COMPATIBLE` where `BREAKING` expected)
- `❌` means wrong in the opposite direction (e.g. `BREAKING` where `COMPATIBLE` expected)
- Tools that ERROR or TIMEOUT on a case are **excluded from the denominator** (so ABICC(dump) scores 20/30, not 20/42)

### Classification changes vs old benchmark

The following cases had incorrect expected verdicts in the pre-PR #71 README and are now fixed:

| Case | Old (wrong) | New (correct) | Reason |
|------|------------|---------------|--------|
| case05_soname | BREAKING | COMPATIBLE | Missing SONAME is a bad practice but binary-compatible; consumers still link |
| case06_visibility | BREAKING | COMPATIBLE | Visibility leak is a policy issue, not a binary break for existing consumers |
| case15_noexcept_change | COMPATIBLE | BREAKING | Removing `noexcept` changes exception spec ABI (GLIBCXX_3.4.21 dependency) |
| case16_inline_to_non_inline | BREAKING | COMPATIBLE | ODR risk is real but no existing binary consumer is broken by the new symbol |

These changes are reflected in `examples/ground_truth.json` and do not affect abicheck scores (it was always correct on all 42).

## TL;DR

| Tool | Correct / Scored | Accuracy | Notes |
|------|-----------------|----------|-------|
| **abicheck (compare)** | **42/42** | **100%** | castxml + ELF, full semantic analysis ³ |
| abicheck (compat)  | 40/42 | 95% | ABICC drop-in; 2 cases use API_BREAK verdict not supported in compat mode |
| abicheck (strict)  | 31/42 | 73% | `--strict-mode full` promotes COMPATIBLE→BREAKING (expected for strict) |
| ABICC (abi-dumper) | 20/30 | 66% | Scored on 30/42 — 12 cases ERROR/TIMEOUT ⁴ |
| ABICC (xml)        | 25/41 | 60% | Scored on 41/42 — case16 TIMEOUT |
| abidiff (ELF)      | 11/42 | 26% | ELF symbol diff only |
| abidiff (+headers) | 11/42 | 26% | Same as ELF — see note below |

## Why compat scores 40/42 (not 42)

`abicheck compat` is an ABICC XML drop-in and follows ABICC's verdict vocabulary:
it can only emit `COMPATIBLE`, `BREAKING`, and `NO_CHANGE`. Cases `case31_enum_rename`
and `case34_access_level` expect `API_BREAK` — a source-level-only break that is binary-
compatible. `compat` has no way to express this distinction, so those two cases are scored
as misses. This is a known, intentional limitation documented in `ground_truth.json`
(`expected_compat` field).

**Use `abicheck compare` (default mode) for full verdict fidelity.**
Use `abicheck compat` as a drop-in for existing ABICC-based pipelines.

## Why strict scores 31/42

`--strict-mode full` (default when `-s`) promotes `COMPATIBLE` → `BREAKING`. This is
intentional behaviour — it matches ABICC's `-strict` flag semantics.
Nine cases where the expected verdict is `COMPATIBLE` (e.g. case03 additive change,
case05 soname addition, case13 symbol versioning) correctly score as misses in strict mode:
they _are_ COMPATIBLE changes, and strict mode deliberately over-reports them.

**Use `--strict-mode api` if you only want to promote true API_BREAK → BREAKING
without false-positives on additive COMPATIBLE changes.**

## Why abicheck (73%) beats ABICC dumper (66%)

ABICC dumper uses `abi-dumper` (Perl + DWARF), which fails on many C++ patterns:
- 12 cases return `ERROR` or `TIMEOUT` (so only 30/42 are scored)
- `case09_cpp_vtable` — 122s TIMEOUT in dumper mode. `abi-compliance-checker`'s vtable
  analysis uses `gcc -fdump-lang-class`; its Perl parser becomes slow on even moderately
  complex virtual class hierarchies.
- `case28/30/31/32/33/34/35/36/40` — ERROR (complex C++ types)

abicheck uses castxml (Clang-based) — correct results on all 42 cases, no timeouts.

## Why abidiff+headers = abidiff (both 11/42)

`abidiff --headers-dir` uses the headers to **filter** which symbols are considered
public API — it doesn't use them to extract type information. Our examples are compiled
with `-fvisibility=default` and have no `visibility("hidden")` annotations in headers,
so the filter changes nothing.

`abidiff` misses type-level changes (struct layout, enum values, vtable, return types)
because it relies solely on DWARF — it doesn't run a compiler or parse AST.
These are fundamental limitations of DWARF-only analysis.

**abicheck uses castxml for full AST-level type analysis → catches all 42 cases.**

## Full results (42 cases)

| Case | Expected | abicheck | compat | strict | abidiff | abidiff+hdr | ABICC(dump) | ABICC(xml) |
|------|----------|----------|--------|--------|---------|-------------|-------------|------------|
| case01_symbol_removal | BREAKING | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| case02_param_type_change | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT | ✅ | ✅ |
| case03_compat_addition | COMPATIBLE | ✅ | ✅ | ❌ BREAKING¹ | ✅ | ✅ | ✅ | ✅ |
| case04_no_change | NO_CHANGE | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT |
| case05_soname | COMPATIBLE | ✅ | ✅ | ❌ BREAKING¹ | ⚠️ BREAKING | ⚠️ BREAKING | ✅ | ✅ |
| case06_visibility | COMPATIBLE | ✅ | ✅ | ❌ BREAKING¹ | ⚠️ BREAKING | ⚠️ BREAKING | ❌ BREAKING | ❌ BREAKING |
| case07_struct_layout | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ NO_CHANGE | ⚠️ COMPAT | ⚠️ COMPAT |
| case08_enum_value_change | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ NO_CHANGE | ✅ | ✅ |
| case09_cpp_vtable | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ NO_CHANGE | ⏱️ TIMEOUT | ✅ |
| case10_return_type | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT | ✅ | ⚠️ COMPAT |
| case11_global_var_type | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT | ✅ | ✅ |
| case12_function_removed | BREAKING | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| case13_symbol_versioning | COMPATIBLE | ✅ | ✅ | ❌ BREAKING¹ | ✅ NO_CHANGE | ✅ NO_CHANGE | ✅ | ✅ |
| case14_cpp_class_size | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT | ✅ | ⚠️ COMPAT |
| case15_noexcept_change | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ⚠️ COMPAT | ⚠️ COMPAT |
| case16_inline_to_non_inline | COMPATIBLE | ✅ | ✅ | ❌ BREAKING¹ | ✅ | ✅ | ❌ ERROR | ⏱️ TIMEOUT |
| case17_template_abi | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT | ⚠️ COMPAT | ⚠️ COMPAT |
| case18_dependency_leak | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT | ⚠️ COMPAT | ⚠️ COMPAT |
| case19_enum_member_removed | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT | ⚠️ COMPAT | ⚠️ COMPAT |
| case20_enum_member_value_changed | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ⚠️ COMPAT | ⚠️ COMPAT |
| case21_method_became_static | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT | ✅ | ✅ |
| case22_method_const_changed | BREAKING | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ COMPAT |
| case23_pure_virtual_added | BREAKING | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ COMPAT |
| case24_union_field_removed | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ⚠️ COMPAT | ⚠️ COMPAT |
| case25_enum_member_added | COMPATIBLE | ✅ | ✅ | ❌ BREAKING¹ | ✅ NO_CHANGE | ✅ NO_CHANGE | ✅ | ✅ |
| case26_union_field_added | BREAKING | ✅ | ✅ | ✅ | ⚠️ COMPAT | ⚠️ COMPAT | ✅ | ✅ |
| case26b_union_field_added_compatible | COMPATIBLE | ✅ | ✅ | ❌ BREAKING¹ | ✅ NO_CHANGE | ✅ NO_CHANGE | ✅ | ✅ |
| case27_symbol_binding_weakened | COMPATIBLE | ✅ | ✅ | ❌ BREAKING¹ | ✅ NO_CHANGE | ✅ NO_CHANGE | ✅ | ✅ |
| case28_typedef_opaque | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ❌ ERROR | ⚠️ COMPAT |
| case29_ifunc_transition | COMPATIBLE | ✅ | ✅ | ❌ BREAKING¹ | ✅ NO_CHANGE | ✅ NO_CHANGE | ✅ | ✅ |
| case30_field_qualifiers | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ❌ ERROR | ⚠️ COMPAT |
| case31_enum_rename | API_BREAK | ✅ | ⚠️ API_BREAK² | ✅ BREAKING | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ❌ ERROR | ⚠️ COMPAT |
| case32_param_defaults | NO_CHANGE | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ ERROR | ⚠️ COMPAT |
| case33_pointer_level | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ❌ ERROR | ⚠️ COMPAT |
| case34_access_level | API_BREAK | ✅ | ⚠️ API_BREAK² | ✅ BREAKING | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ❌ ERROR | ⚠️ COMPAT |
| case35_field_rename | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ❌ ERROR | ⚠️ COMPAT |
| case36_anon_struct | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ❌ ERROR | ⚠️ COMPAT |
| case37_base_class | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ⚠️ COMPAT | ⚠️ COMPAT |
| case38_virtual_methods | BREAKING | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| case39_var_const | BREAKING | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ ERROR | ✅ |
| case40_field_layout | BREAKING | ✅ | ✅ | ✅ | ⚠️ NO_CHANGE | ⚠️ NO_CHANGE | ❌ ERROR | ⚠️ COMPAT |
| case41_type_changes | BREAKING | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

Legend: ✅ correct · ⚠️ wrong/undercounted (e.g. COMPATIBLE when BREAKING expected) · ❌ wrong in opposite direction · ⏱️ timed out (cutoff: 120s)
`API_BREAK` = source-level-only break, binary-compatible (e.g. access level change, enum rename). Only `abicheck compare` emits this verdict.

¹ `strict` false positive: COMPATIBLE → BREAKING is expected with `--strict-mode full`; use `--strict-mode api` to avoid.  
² `compat` known limitation: API_BREAK verdict not supported; maps to COMPATIBLE (scored as miss).  
³ Test cases authored for this benchmark; gcc 13, x86_64 Linux. Run `python3 scripts/benchmark_comparison.py` to reproduce.  
⁴ ABICC(dump) denominator is 30 (not 42) because 12 cases produced ERROR or TIMEOUT and are excluded. See methodology above.

## Timing

| Tool | Total (42 cases) | Notes |
|------|-----------------|-------|
| abicheck | ~212s | castxml per case; sequential, parallelisable |
| abicheck compat | ~79s | XML descriptor mode |
| abicheck strict | ~78s | same as compat + verdict promotion |
| abidiff | ~2.5s | ELF+DWARF, very fast |
| abidiff+headers | ~3.9s | same |
| ABICC (dumper) | ~294s | abi-dumper + abi-compliance-checker per case |
| ABICC (xml) | ~445s | GCC compilation per case; case09+case16 TIMEOUT |

> Measured on: Ubuntu 22.04, 8 vCPU, 32GB RAM (onedal-build, AWS t3.2xlarge equivalent).
> All runs are sequential (one case at a time). Parallelising abicheck across CPUs
> would reduce its wall time proportionally.

## ABICC XML mode: why so slow and inaccurate

ABICC XML mode (`-old v1.xml -new v2.xml`) invokes GCC to compile headers for type extraction.
Problems:
1. **Slow**: GCC invocation per case, even for 5-line headers
2. **Timeouts**: `case16_inline_to_non_inline` reliably hits 120s
3. **Inaccurate**: when the descriptor points to a directory, `abi-compliance-checker`
   includes _all_ `.h` files found there — including duplicates from build subdirs,
   causing redefinition errors and wrong verdicts
4. **GCC bug #78040**: does not work correctly with GCC 6+ (prints warning on every run)

abicheck avoids all of this by using castxml (Clang AST, single pass, no GCC).

## Run yourself

```bash
# Full benchmark (all 42 cases, all tools)
python3 scripts/benchmark_comparison.py

# Select specific cases
python3 scripts/benchmark_comparison.py --cases case01 case09 case21

# Select specific tools
python3 scripts/benchmark_comparison.py --tools abicheck abidiff

# Skip ABICC (CI-friendly, ~15s total)
python3 scripts/benchmark_comparison.py --skip-abicc

# ABICC timeout (default 120s)
python3 scripts/benchmark_comparison.py --abicc-timeout 60

# abicheck compat strict mode
python3 scripts/benchmark_comparison.py --tools abicheck_compat abicheck_strict
```

## Environment

Tested on: Ubuntu 22.04, 8 vCPU, 32GB RAM (onedal-build)  
castxml 0.6+, gcc 13, abidiff 2.4+, abi-compliance-checker 2.3, abi-dumper 1.2
