# Case 06: Symbol Visibility Leak

**Category:** Visibility | **Verdict:** 🟡 BAD PRACTICE

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

Running `abicheck dump libv1.so` (without headers) + comparing to `libv2.so`:

- **`VISIBILITY_LEAK`** (BAD PRACTICE / COMPATIBLE): `libv1.so` exports
  internal-looking symbols (`internal_helper`, `another_impl`) without
  `-fvisibility=hidden`. Reported on the **old library**, not the transition.
- **`FUNC_REMOVED_ELF_ONLY`** (COMPATIBLE): ELF-only symbols disappear in `libv2.so`.
  Classified as compatible because — without header information — we cannot tell
  whether a disappearing ELF-only symbol was a real public function or an internal
  symbol being correctly hidden.

**Overall verdict: COMPATIBLE** (the library still works; the bad practice was in v1).

## What this case does NOT cover

If actual consumers were linked against `libv1.so` and called `internal_helper`
directly, and `libv2.so` hides it → those consumers will get a runtime
`symbol lookup error`. **But that is a different case** — it is covered by
`case01_symbol_removal` (FUNC_REMOVED / BREAKING). The root cause there is the
visibility leak in v1; case06 detects that root cause.

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

# Run abicheck (no headers — ELF-only mode)
python3 -m abicheck.cli dump examples/case06_visibility/libv1.so -o /tmp/v1.json
python3 -m abicheck.cli dump examples/case06_visibility/libv2.so -o /tmp/v2.json
python3 -m abicheck.cli compare /tmp/v1.json /tmp/v2.json
# → COMPATIBLE + VISIBILITY_LEAK warning on libv1.so
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
