# Limitations & Known Boundaries

`abicheck` is designed to catch real ABI breaks with high accuracy, but has specific
limitations you should understand before relying on it in production.

---

## Header / Binary Mismatch Risk

**The most important limitation.** `abicheck` uses `castxml` to parse headers and
compares the result against the compiled `.so`. If the headers passed to analysis
don't exactly match what was compiled, results will be unreliable.

**This happens when:**
- You pass generic system headers but the library was compiled with custom `#define` flags
- Preprocessor macros change the public API surface (`#ifdef FEATURE_X`)
- Third-party dependency headers differ between versions (causing dependency ABI leaks to go undetected)
- Platform-specific code paths (`#ifdef __linux__`) differ between compile and analysis environments

**Mitigation:**
- Always use the exact same headers that were used to build the `.so`
- Pass all relevant compile-time defines via `castxml` flags
- Use `--strict` mode to surface more potential issues
- Cross-check with `abicheck compat` (ABICC mode) for independent validation

---

## Stripped Production Binaries

Tiers 3 and 4 (DWARF layout + Advanced DWARF) require debug symbols (`-g`).
Production `.so` files are typically stripped — in this case:

- Struct field offset changes may be missed (Tier 3 unavailable)
- Calling convention drift, struct packing changes not detected (Tier 4 unavailable)
- Tier 1 (castxml/headers) and Tier 2 (ELF symbols) still run — most critical breaks caught

**Mitigation:** Use CI/staging debug builds for deep analysis where possible.
For production binaries, combine `abicheck` with `abicheck compat` ABICC+headers mode.

---

## Template Instantiation

C++ template instantiations with complex type parameters can produce unexpected results:
- Explicit instantiations in `.so` are analyzed; implicit instantiations in headers are not
- Template specializations may not all be captured
- `case17_template_abi` in the examples demonstrates a detectable case

---

## `COMPATIBLE` Does Not Mean "Invisible"

`COMPATIBLE` changes are detected and reported — they are not silent. Examples:
- Adding a new export symbol is `COMPATIBLE` but changes the library's API surface
- Enum member addition is `COMPATIBLE` but can affect switch statement completeness

Use `--warn-newsym` to treat new symbols as blocking if your policy requires it.

---

## `compat` Mode Verdict Limitations

`abicheck compat` follows ABICC's verdict vocabulary: it cannot emit `API_BREAK`.
Source-level-only breaks (e.g. `case31_enum_rename`, `case34_access_level`) will be
reported as `COMPATIBLE` in `compat` mode. Use `abicheck compare` for full verdict fidelity.

---

## Inline / Header-Only Code

Functions defined entirely in headers (inline, `constexpr`) may not appear in the `.so`
symbol table. `abicheck` analyzes the public exported ABI — header-only changes that
don't affect exported symbols will not be detected.

---

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for a diagnostic decision tree
covering common false positives, false negatives, and unexpected verdicts.
