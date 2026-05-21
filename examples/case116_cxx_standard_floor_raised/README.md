# case116 — C++ standard floor raised (API_BREAK)

## What this case demonstrates

`v1.h` works under C++17. `v2.h` adds a `requires` clause to the same
public template — the declaration set is unchanged, but consumers
whose toolchain still targets C++17 cannot include the header at all.

## Why a dedicated detector

A symbol diff sees nothing: same names, same signatures, same vtables.
The breakage is silent until a consumer actually rebuilds against the
new headers. The matrix-aware `CXX_STANDARD_FLOOR_RAISED` finding is
emitted when the probe harness records the per-configuration `cxx_std`
and the minimum floor moves up between releases.

## Expected verdict

`API_BREAK` — source break for consumers below the new standard floor.
