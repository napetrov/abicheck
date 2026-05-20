# Case 107: `task_scheduler_init` Removed (oneTBB historical break)

**Category:** Class Removal | **Verdict:** 🔴 BREAKING

## What breaks

An entire publicly-exported class — `task_scheduler_init` — is removed in v2.
Every consumer that referenced the class (constructed it, called its members,
or held it by value) gets `undefined symbol` at load time, and source code
fails to compile against the new headers.

## Why this is a oneTBB-flavored break

This is the single largest hard ABI break in TBB's history: classic TBB
deprecated `tbb::task_scheduler_init` in 2020 and *removed* it in oneTBB
2021.1, alongside the entire `tbb::task` low-level API. The replacements
(`tbb::global_control`, `tbb::task_arena`) have different lifetimes and
semantics.

Real-world consequence: every Boost build that linked TBB, every HPC code
using `task_scheduler_init` directly, and every downstream package had to
either pin to classic TBB or rewrite its initialization path.

## Code diff

| v1 | v2 |
|----|------|
| `class task_scheduler_init { ... };` | *(removed)* |
| `task_scheduler_init(int)` | *(removed)* |
| `terminate()` / `is_active()` | *(removed)* |

## How abicheck catches it

The existing `FUNC_REMOVED` / `TYPE_REMOVED` detectors fire on every
public symbol the class exported. This case exists as a *named regression
fixture* so the canonical TBB removal pattern stays exercised in CI.

## How to fix

Don't remove publicly-exported classes in a minor release. The oneTBB
migration showed the only safe path:
1. Major SONAME bump (`libtbb.so.2` → `libtbb.so.12`).
2. Concurrent shipping of compatibility headers via a separate package
   (`tbb_preview`) for a transition release.
3. Strong documentation of the migration with mechanical replacements.

## References

- [oneTBB migration guide](https://oneapi-spec.uxlfoundation.org/specifications/oneapi/latest/elements/oneTBB/source/intro/limitations)
- [Removal in oneTBB 2021.1 release notes](https://github.com/uxlfoundation/oneTBB/releases)
