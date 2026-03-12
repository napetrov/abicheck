# Case 43: Base Class Member Added

**Category:** C++ Layout | **Verdict:** 🔴 BREAKING

## What breaks

A data member is added to a base class (`Base`). This shifts the memory layout of
**all derived classes** — their fields move to higher offsets. Any consumer binary
compiled against v1 headers will read `Derived::value` at the wrong offset when
linked against the v2 library, causing silent data corruption or crashes.

## Why abidiff catches it

abidiff reports `Added_Base_Class_Data_Member` and exits with code **4** (ABI change).
Note: abidiff exits 4 (not 12) because this is a layout change, not a symbol removal.
abicheck detects: `TYPE_SIZE_CHANGED` on `Base`, `TYPE_FIELD_OFFSET_CHANGED` on `Derived::value`.

## Code diff

| v1.hpp | v2.hpp |
|--------|--------|
| `class Base { int base_id; ... };` | `class Base { int base_id; int extra_field; ... };` |
| `class Derived : public Base { int value; };` | `class Derived : public Base { int value; };` |
| `sizeof(Derived)` ≈ 20 bytes | `sizeof(Derived)` ≈ 24 bytes — `value` shifts by 4 |

## Real Failure Demo

**Severity: 🔴 CRITICAL**

**Scenario:** compile app against v1, swap in v2 `.so` — `Derived::value` is read at wrong offset.

```bash
# Build libraries
g++ -shared -fPIC -g v1.cpp -o libv1.so
g++ -shared -fPIC -g v2.cpp -o libv2.so

# The size shift is immediately visible:
python3 -c "
import ctypes, subprocess, tempfile, os, sys

# Quick check via abidw
"

abidw --out-file v1.abi libv1.so
abidw --out-file v2.abi libv2.so
abidiff v1.abi v2.abi
echo "exit: $?"   # → 4 (ABI change: base class data member added)
```

## Reproduce manually

```bash
g++ -shared -fPIC -g v1.cpp -o libv1.so
g++ -shared -fPIC -g v2.cpp -o libv2.so
abidw --headers-dir . --out-file v1.abi libv1.so
abidw --headers-dir . --out-file v2.abi libv2.so
abidiff v1.abi v2.abi
echo "exit: $?"   # → 4
```

## How to fix

Never add data members to a base class that has derived classes in the public API.
Options:
1. **Pimpl on Base** — put the new field in a private `Impl*` struct.
2. **SONAME bump** — major version bump + abi_tag if breaking change is unavoidable.
3. **Add to Derived, not Base** — if only one derived class needs the field.
