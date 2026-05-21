// case116 v2 — header now requires C++20 (uses a `requires`
// expression). Consumers still building with C++17 cannot include
// this header at all.
//
// The dedicated CXX_STANDARD_FLOOR_RAISED finding is emitted by the
// matrix detector when the probe harness's manifest records the
// per-configuration `cxx_std` and the minimum floor moves up between
// releases. The static example fixture here documents the failure mode
// for reviewers and serves as an integration smoke test.
#pragma once

namespace lib {

template <typename T>
    requires requires(T t) { ++t; }
T identity(T x) { return x; }

void print_int(int x);

} // namespace lib
