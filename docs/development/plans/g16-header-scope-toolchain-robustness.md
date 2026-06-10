# G16 — Header-scoped source-mode toolchain robustness & actionable diagnostics

**Registry:** `UC-TC-header-scope-robustness` (`planned`)
**Effort:** M · **Risk:** medium (host-toolchain matrix is large; castxml/clang quirks)

## Problem

Header-scoped scans (`--headers`, the castxml source path in
`abicheck/dumper_castxml.py`) are the only way abicheck can separate *public
source API* from *private/internal* surface — the single most-requested
disambiguation in the real-world scan campaign. But in the 2026-06 real-world
cron the header-scoped re-run **aborted before any ABI comparison** in 21
separate issue records, always for the same small family of host-toolchain
parse failures, never for an abicheck logic bug:

- **glibc sized-float types** — `unknown type name '_Float32'` (also
  `_Float64`/`_Float128`) when castxml's clang frontend parses the host
  `/usr/include/stdlib.h` / `<math.h>` pulled in transitively
  (`ISSUE-RW-20260606-1539-04`, `-1509-03`, `-1645-03`, libuv/krb5/benchmark/fmt).
- **GCC 13 libstdc++ attribute** — `__assume__` attribute parse failure through
  C++ system headers (`ISSUE-RW-20260606-1509-03`).
- **`--lang c` + `extern "C"`** — C headers guarded by
  `#ifdef __cplusplus extern "C"` fail in explicit `--lang c` mode even though
  the guard is correct, because castxml always drives clang in a C++-ish mode
  (`ISSUE-RW-20260606-1539-04`, `-1645-03`).

The net effect is that the *binary-only* verdict (correctly `BREAKING` on a
removed export) cannot be contrasted against a *public-header-scoped* verdict,
so the campaign cannot tell "real public-API break" from "internal/private
export churn" for C/C++ libraries on a stock GCC/glibc host. abicheck already
has a precise hint for one symptom (the `--lang c` class/namespace mismatch in
`_validate_castxml_output`), which proves the pattern works — the remaining
symptoms just have no equivalent guidance and surface as a raw
`castxml failed (exit N)` stderr dump.

This is **not** the G4 problem. G4 adds a *libclang AST extractor* to observe
source constructs castxml cannot emit (concepts, `explicit`, ctor mangling).
G16 is about making the *existing* castxml header path **survive a stock host
toolchain** and, when it cannot, **fail with an actionable, single-line hint**
instead of an opaque compiler error.

## Goal & acceptance criteria

- [x] A parse-failure classifier recognises the known host-header symptoms
      (`_Float32`/`_Float64`/`_Float128`, GCC `__assume__`, the `--lang c` +
      `extern "C"` case) in castxml stderr and surfaces a specific,
      copy-pasteable remediation. *Done:* `_castxml_failure_hint` in
      `abicheck/dumper.py`; the hint is appended to the raised `SnapshotError`.
- [x] At least one known symptom is *worked around* rather than only diagnosed:
      inject the minimal flag(s) that let a stock GCC/glibc host parse the
      sized-float declarations through castxml's clang frontend. *Done:*
      `_castxml_dump` auto-retries once with `_FLOATN_SHIM_DEFINES` (`-D_Float32=float`
      …) after a sized-float failure; healthy hosts are unaffected (retry only
      fires on the matching failure).
- [ ] `abicheck compare --headers` over a tiny header that transitively includes
      `<math.h>` succeeds (or degrades with the actionable hint) on the CI host,
      asserted end-to-end. *Remaining* (needs the `integration` toolchain).
- [x] The diagnostic text and retry are unit-tested against captured stderr
      snippets (no live compiler needed). *Done:*
      `tests/test_castxml_toolchain_robustness.py`.
- [ ] Promote to a dedicated `HeaderToolchainError` so callers can branch on the
      class, and add a real `__assume__` workaround (currently diagnosed only).
      *Remaining.*

## Design

1. **Classifier** — extend `_validate_castxml_output` (and the surrounding
   failure path in `dumper_castxml.py`) with a `_classify_castxml_failure(stderr)`
   helper that maps known stderr signatures → a remediation string, mirroring the
   existing `--lang c` hint. Raise a dedicated `HeaderToolchainError`
   (subclass of the current error) so callers/CLI can present it cleanly.
2. **Workaround flags** — in `_build_castxml_command`, when the resolved compiler
   is GCC/glibc, inject the minimal known-good shim (candidate:
   `-resource-dir`/`-isystem` pointing at a sized-float-safe header set, or the
   feature-test `-D` that gates `_FloatN`). Keep it opt-out and additive so
   existing successful runs are unchanged.
3. **CLI surfacing** — ensure the `compare`/`dump --headers` path renders the
   `HeaderToolchainError` remediation as a single actionable line (not a 2 000-char
   stderr blob) and exits with the existing tooling-error code.

## Files & surfaces

- `abicheck/dumper_castxml.py` — `_build_castxml_command`,
  `_validate_castxml_output`, new `_classify_castxml_failure`.
- `abicheck/errors.py` — `HeaderToolchainError`.
- `abicheck/cli.py` / `abicheck/service.py` — render the remediation line.

## Tests

- `tests/test_castxml_errors.py` — extend with the captured stderr signatures
  (`_Float32`, `__assume__`, `--lang c` + `extern "C"`) → assert the specific
  remediation text (message-only, no compiler).
- `tests/test_header_scope_toolchain.py` (new, `integration`) — a header that
  `#include <math.h>` parses (or yields the hint) end-to-end on a GCC/glibc host.

## Example fixtures

- A minimal `examples/`-style C header that transitively pulls in sized-float
  types, used by the integration test to prove the host-header path survives.

## Effort & risk

M. The classifier + message tests are small and high-value (they turn 21
dead-end campaign runs into one-line, user-fixable diagnostics). The actual
*workaround* is the risky part — castxml/clang resource-dir behaviour varies by
host GCC/clang version — so it is gated behind the opt-out flag and proven on the
CI host only, with the diagnostic as the guaranteed fallback.

## Out of scope

- Observing source constructs castxml cannot emit (concepts/`explicit`/ctor
  mangling) — that is **G4**.
- Shipping a bundled compiler/sysroot. G16 makes the *host* toolchain usable or
  clearly diagnoses it; it does not vendor a toolchain.
