# Case 06: Symbol Visibility Leak

**Category:** Visibility | **Verdict:** 🔴 BREAKING (bad practice)

> **ground_truth.json:** `expected: BREAKING`, `category: breaking`
> **checker_policy.py:** `FUNC_REMOVED` ∈ `BREAKING_KINDS`

## What this case is about

This case detects a **single-library quality issue**: a library that was compiled
without `-fvisibility=hidden` unintentionally exports all internal symbols as part
of its public ABI surface.

**This is NOT a comparison between two libraries.**
The bad practice lives in `libv1.so` (the "bad" library) *alone*.
`libv2.so` (the "good" library) is provided only as the correct reference —
it shows how the library *should* look.

## Why exposing internal symbols is bad practice

- Every internal symbol (`internal_helper`, `another_impl`, etc.) accidentally
  becomes part of the public ABI contract.
- Any future refactor of internal helpers — rename, split, remove — risks being
  detected as an ABI break or actually breaking consumers that mistakenly linked
  against them.
- Bloated `.dynsym` tables slow dynamic linker startup (symbol resolution scan).

## What abicheck detects

Running `abicheck dump -H bad.c libv1.so` + comparing to `abicheck dump -H good.c libv2.so`:

- **`VISIBILITY_LEAK`** (BAD PRACTICE / COMPATIBLE): `libv1.so` exports
  internal-looking symbols (`internal_helper`, `another_impl`) without
  `-fvisibility=hidden`. Reported on the **old library**, not the transition.
- **`FUNC_REMOVED`** (BREAKING): `another_impl()` is declared in `bad.c` but
  absent from `good.c` entirely — the function was removed from both the header
  and the library. Any consumer that called `another_impl` will fail to load.
- **`FUNC_VISIBILITY_CHANGED`** (BREAKING): `internal_helper()` changes from
  default to hidden visibility — it disappears from `.dynsym`.

**Overall verdict: BREAKING** — removing or hiding previously-exported symbols
is an ABI break for any consumer that depended on them, even if the symbols
were only exported by accident.

> **Note:** In ELF-only mode (without `-H`), both removals are classified as
> `FUNC_REMOVED_ELF_ONLY` (COMPATIBLE) because the tool cannot distinguish
> intentional public API from accidentally-leaked internals. Use `-H` to get
> the accurate BREAKING verdict.

## Dual nature of this case

This case is both a **bad practice** (v1 leaked internal symbols) and a **breaking
change** (v2 removes those symbols from the dynamic table). The root cause is the
visibility leak in v1; fixing it in v2 is the right thing to do, but it requires
a SONAME bump or a transition plan.

## How to reproduce

```bash
# Build
make -C examples/case06_visibility

# Check libv1.so (bad — leaks internal symbols)
nm --dynamic --defined-only examples/case06_visibility/libv1.so
# → public_api, internal_helper, another_impl  ← leak!

# Check libv2.so (good — only public API)
nm --dynamic --defined-only examples/case06_visibility/libv2.so
# → public_api only  ← correct

# Run abicheck (with headers for accurate detection)
python3 -m abicheck.cli dump examples/case06_visibility/libv1.so \
    -H examples/case06_visibility/bad.c -o /tmp/v1.json
python3 -m abicheck.cli dump examples/case06_visibility/libv2.so \
    -H examples/case06_visibility/good.c -o /tmp/v2.json
python3 -m abicheck.cli compare /tmp/v1.json /tmp/v2.json
# → BREAKING (FUNC_REMOVED: another_impl) + VISIBILITY_LEAK warning on libv1.so
```

## How to fix

Add `-fvisibility=hidden` to build flags and annotate every intended public
function with `__attribute__((visibility("default")))`. Use a `FOO_EXPORT` macro:

```c
#define FOO_EXPORT __attribute__((visibility("default")))
FOO_EXPORT int public_api(void);  // exported
static int internal_helper(void); // or just leave it static
```

## Real-world example

Qt, GCC libstdc++, LLVM, and most large C++ projects gate their public API with
visibility macros (`Q_DECL_EXPORT`, `_GLIBCXX_VISIBILITY`) precisely to avoid
this. `-fvisibility=hidden` is standard practice since GCC 4.

## References

- [GCC visibility](https://gcc.gnu.org/wiki/Visibility)
- [libabigail `abidiff` manual](https://sourceware.org/libabigail/manual/abidiff.html)
