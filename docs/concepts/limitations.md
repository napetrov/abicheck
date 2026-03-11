# Limitations & Known Boundaries

`abicheck` is designed to catch real ABI and API breaks with high accuracy, but has specific
limitations you should understand before relying on it in production.

---

## Header / Binary Mismatch Risk

**The most important limitation.** `abicheck` uses `castxml` to parse headers and
compares the result against the compiled `.so`. If the headers passed to analysis
don't exactly match what was compiled, results will be unreliable.

**This happens when:**
- You pass generic system headers but the library was compiled with custom `#define` flags
- Preprocessor macros change the public API surface (`#ifdef FEATURE_X`)
- Third-party dependency headers differ between versions
- Platform-specific code paths (`#ifdef __linux__`) differ between compile and analysis environments

**Mitigation:**
- Always use the exact same headers that were used to build the `.so`
- Pass compile-time defines to castxml: `abicheck dump libfoo.so -H foo.h --castxml-arg=-DFEATURE_X`
- For `abicheck compat`, use `-s` (strict mode) to promote `COMPATIBLE`/`API_BREAK` to BREAKING:
  `abicheck compat -lib foo -old OLD.xml -new NEW.xml -s`
  (use `--strict-mode api` to promote only `API_BREAK`; `-s` is not available on `abicheck compare`)
- Cross-check with `abicheck compat` (ABICC mode) for independent validation

---

## Stripped Production Binaries

Tiers 3 and 4 (DWARF layout + Advanced DWARF) require debug symbols (`-g`).
Production `.so` files are typically stripped — in this case:

- Struct field offset changes may be missed (Tier 3 unavailable)
- Calling convention drift, struct packing changes not detected (Tier 4 unavailable)
- Tier 1 (castxml/headers) and Tier 2 (ELF symbols) still run — most critical breaks caught

**Mitigation:** Use CI/staging debug builds (`CFLAGS=-g`) for deep analysis where possible.
For production binaries, Tier 1+2 analysis covers the majority of real-world ABI breaks.

---

## Template Instantiation

C++ template instantiations with complex type parameters can produce unexpected results:
- Explicit instantiations in `.so` are analyzed; implicit instantiations in headers are not
- Template specializations may not all be captured
- `case17_template_abi` in the examples demonstrates a detectable case

**Mitigation:** Use explicit template instantiation (`template class Foo<int>;`) for
ABI-sensitive types you want to guarantee are tracked.

---

## `COMPATIBLE` Does Not Mean "Invisible"

`COMPATIBLE` changes are detected and reported — they are not silent. Examples:
- Adding a new export symbol is `COMPATIBLE` but grows the library's API surface
  (relevant for semver policy: additive changes may still require a minor version bump)
- Enum member addition is `COMPATIBLE` but can affect exhaustive `switch` statements

For `abicheck compat` pipelines, use `-s` to treat `COMPATIBLE` as blocking.
For `abicheck compare` pipelines, enforce via CI exit code logic (treat exit `2` as failure).

---

## `compat` Mode Verdict Limitations

`abicheck compat` *does* emit exit code `2` for `API_BREAK` conditions, but the
report text uses ABICC-style phrasing rather than a bare `API_BREAK` verdict string.
Source-level-only breaks (e.g. `case31_enum_rename`, `case34_access_level`) will
appear as warnings in the compat HTML/text report.

Use `abicheck compare --format json` for precise machine-readable `API_BREAK` verdicts.

---

## Inline / Header-Only Code

Functions defined entirely in headers (inline, `constexpr`, template) may not appear
in the `.so` symbol table. `abicheck` analyzes the public exported ABI — header-only
changes that don't affect exported symbols will not be detected.

---

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for a diagnostic decision tree
covering common false positives, false negatives, and unexpected verdicts.
