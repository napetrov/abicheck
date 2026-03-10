# Status Alignment Gap Report (Ground Truth vs README Labels)

This document captures **intentional and unintentional status drift** between:

- `examples/ground_truth.json` expected verdict (single source of truth),
- top-line `**Verdict:**` in each case README, and
- optional `**abicheck verdict:**` line in README.

## Summary

- Total cases checked: **42**.
- Cases with at least one mismatch: **14**.

## Why these gaps happen

1. Some READMEs use descriptive labels like `ABI CHANGE` / `BAD PRACTICE` instead of canonical verdict enums.
2. Some cases intentionally document tool-mode nuance (e.g., headers-only vs ELF-only), while ground truth stores one final policy verdict.
3. A few READMEs still contain mixed labels (`SOURCE_BREAK` in title line but `abicheck verdict: BREAKING`).

## Mismatch inventory

| Case | ground_truth expected | README Verdict (normalized) | README abicheck verdict (normalized) | Notes |
|---|---:|---:|---:|---|
| `case02_param_type_change` | `BREAKING` | `UNKNOWN` | `UNKNOWN` | README verdict uses non-canonical wording; no/unclear abicheck verdict line |
| `case05_soname` | `COMPATIBLE` | `UNKNOWN` | `UNKNOWN` | README verdict uses non-canonical wording; no/unclear abicheck verdict line |
| `case06_visibility` | `COMPATIBLE` | `UNKNOWN` | `UNKNOWN` | README verdict uses non-canonical wording; no/unclear abicheck verdict line |
| `case07_struct_layout` | `BREAKING` | `UNKNOWN` | `UNKNOWN` | README verdict uses non-canonical wording; no/unclear abicheck verdict line |
| `case08_enum_value_change` | `BREAKING` | `UNKNOWN` | `UNKNOWN` | README verdict uses non-canonical wording; no/unclear abicheck verdict line |
| `case09_cpp_vtable` | `BREAKING` | `UNKNOWN` | `UNKNOWN` | README verdict uses non-canonical wording; no/unclear abicheck verdict line |
| `case10_return_type` | `BREAKING` | `UNKNOWN` | `UNKNOWN` | README verdict uses non-canonical wording; no/unclear abicheck verdict line |
| `case11_global_var_type` | `BREAKING` | `UNKNOWN` | `UNKNOWN` | README verdict uses non-canonical wording; no/unclear abicheck verdict line |
| `case14_cpp_class_size` | `BREAKING` | `UNKNOWN` | `UNKNOWN` | README verdict uses non-canonical wording; no/unclear abicheck verdict line |
| `case19_enum_member_removed` | `BREAKING` | `SOURCE_BREAK` | `BREAKING` | top-line verdict conflicts with ground truth |
| `case20_enum_member_value_changed` | `BREAKING` | `SOURCE_BREAK` | `BREAKING` | top-line verdict conflicts with ground truth |
| `case28_typedef_opaque` | `BREAKING` | `SOURCE_BREAK` | `UNKNOWN` | no/unclear abicheck verdict line; top-line verdict conflicts with ground truth |
| `case34_access_level` | `SOURCE_BREAK` | `SOURCE_BREAK` | `NO_CHANGE` | abicheck verdict line conflicts with ground truth |
| `case39_var_const` | `BREAKING` | `NO_CHANGE` | `UNKNOWN` | no/unclear abicheck verdict line; top-line verdict conflicts with ground truth |

## Priority fix set for next cycle

### P0 (direct contradiction)

- `case19_enum_member_removed`: top-line `SOURCE_BREAK` vs expected `BREAKING`.
- `case20_enum_member_value_changed`: top-line `SOURCE_BREAK` vs expected `BREAKING`.
- `case34_access_level`: mixed tool-mode line includes `NO_CHANGE` while expected is `SOURCE_BREAK`.
- `case39_var_const`: mixed top-line wording should be normalized to final expected `BREAKING`.

### P1 (canonicalization needed, semantics mostly clear)

- Cases using `ABI CHANGE` / `BAD PRACTICE` labels should map explicitly to final canonical verdict enum in first line.
- Keep nuance in a separate line: `Tool-mode notes` or `Policy notes`, without replacing final canonical verdict.

## Recommended alignment rule

Use a strict 2-line header for every case README:

1. `**Final verdict (ground truth): <BREAKING|COMPATIBLE|NO_CHANGE|SOURCE_BREAK>**`
2. `**Tool-mode notes:** ...` (optional, free-form nuance)

This preserves educational nuance while keeping machine/human labels consistent.