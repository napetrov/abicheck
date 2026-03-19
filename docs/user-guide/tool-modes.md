# ABI Tool Modes Reference

This document explains the three modes used for ABI analysis in `abicheck`,
their correct names (as used in ABICC official documentation), requirements,
and limitations.

---

## Mode Overview

| Mode | Official name | Compiler needed? | Debug info needed? | Headers needed? |
|------|--------------|:----------------:|:------------------:|:---------------:|
| abidiff + headers | `abidiff` (libabigail) | ❌ | optional (improves accuracy) | ✅ always |
| ABICC+headers (ABICC Usage #2) | Original / headers mode | ✅ **GCC only** | ❌ | ✅ |
| ABICC+dump (ABICC Usage #1) | abi-dumper / binary mode | ❌ | ✅ (`-g -Og`) | ❌ (optional) |

---

## Decision Flowchart

```
[Project policy] PUBLIC HEADERS are mandatory for analysis
│
├─ headers missing → fail fast / fetch devel/include package first
│
└─ headers available
    │
    Was the .so compiled with -g (debug symbols)?
    │
    ├─ NO (production/stripped .so)
    │
    │   Use abidiff+headers + ABICC+headers (ABICC Usage #2) (combined verdict)
    │   Any break from either → flag as ABI-breaking
    │
    └─ YES (CI/staging debug build)

        Use abidiff+headers + ABICC+dump (ABICC Usage #1) (combined verdict)
        Most accurate: DWARF ground truth for types
        (no compiler needed — abi-dumper reads binary directly)
```

> **Production default:** abidiff+headers + ABICC+headers (ABICC Usage #2).
> Production `.so` files have no debug info → Usage #1 unavailable.

---

## abidiff + headers (libabigail)

### Overview

`abidiff` from **libabigail** compares two `.so` files using their ELF symbol tables
and optionally DWARF debug sections. **We always pass headers** via `--headers-dir`
to improve type resolution.

### How it works

```
libv1.so ──► abidw --headers-dir include/ ──► v1.xml ──┐
                                                         ├──► abidiff ──► report
libv2.so ──► abidw --headers-dir include/ ──► v2.xml ──┘
```

### Requirements

| Requirement | Mandatory? | Notes |
|-------------|-----------|-------|
| Two `.so` files | ✅ | Core input |
| Headers (`--headers-dir`) | ✅ our policy | Greatly improves type resolution |
| DWARF debug info (`-g`) | ❌ optional | Provides additional type layout info |
| Compiler | ❌ | Not needed |

### What it catches

- ✅ Symbol removal/addition
- ✅ Type layout changes (struct/class field changes) — with DWARF or headers
- ✅ vtable changes — with DWARF
- ✅ Return type, parameter type changes — with DWARF/headers
- ✅ Enum value changes
- ✅ ELF-only symbol changes (visibility, binding)

### What it misses

- ❌ `noexcept` specifier (not in DWARF or ELF)
- ❌ `inline` → non-inline ODR changes (inline functions absent from `.so`)
- ❌ C++ `[[nodiscard]]`, `[[deprecated]]`, `explicit` attribute changes
- ❌ Template instantiation details without DWARF
- ❌ Dependency ABI leaks (transitive header type changes) without DWARF

### Usage

```bash
sudo apt-get install abigail-tools

abidw --headers-dir include/ --out-file v1.xml libv1.so
abidw --headers-dir include/ --out-file v2.xml libv2.so
abidiff v1.xml v2.xml
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | No ABI change |
| 4 | ABI change (type/layout diff or compatible addition) |
| 12 | Breaking change (symbol removed) |

---

## ABICC+headers (ABICC Usage #2 — Original / Headers Mode)

> This is what `abi-compliance-checker` calls **USAGE #2 (ORIGINAL)** in its docs.

### Overview

ABICC receives an XML descriptor pointing to the `.so` and headers directory. It uses
**GCC** to compile the headers, extract the full C++ AST, compute type layouts, and
build an ABI dump. Then it compares two such dumps.

### How it works

```
OLD.xml (headers + .so) ──► abi-compliance-checker ──► ABI-old.dump ──┐
                                 (compiles via GCC)                     ├──► report
NEW.xml (headers + .so) ──► abi-compliance-checker ──► ABI-new.dump ──┘
```

### Requirements

| Requirement | Mandatory? | Notes |
|-------------|-----------|-------|
| Two `.so` files | ✅ | |
| Headers | ✅ | The main input for ABI description |
| `abi-compliance-checker` | ✅ | |
| **GCC** | ✅ **GCC only** | ABICC calls GCC internally to compile headers. Proprietary compilers (`icpx`/`icc`) and Clang are **not supported**. |
| DWARF debug info | ❌ | Not needed — headers provide type information |

> **Note:** GCC must be installed even if the library itself is built
> with a different compiler (e.g. `icpx`). ABICC only uses GCC to parse headers, not to compile the library.

### What it catches (beyond abidiff)

- ✅ Everything abidiff catches (with headers as source)
- ✅ `noexcept` specifier changes
- ✅ `inline` → non-inline ODR (symbol absent from v1 .so, appears in v2)
- ✅ C++ attribute changes (`[[nodiscard]]`, `explicit`, etc.)
- ✅ Template instantiation ABI via AST
- ✅ Dependency ABI leaks (if transitive headers are included)
- ✅ Works on stripped production `.so` (no `-g` needed)

### What it misses

- ❌ ELF-only symbol visibility changes (no symbol table analysis)
- ❌ Anonymous struct/union not expressible in headers
- ❌ Types resolved differently by `#ifdef`/macro guards at compile time (header AST may differ from actual compiled result)

### Usage

```bash
sudo apt-get install abi-compliance-checker gcc

# Create OLD.xml descriptor:
cat > OLD.xml << EOF
<version>1.0</version>
<headers>/path/to/v1/include/</headers>
<libs>/path/to/libfoo_v1.so</libs>
EOF

# Create NEW.xml similarly, then compare:
abi-compliance-checker -lib libfoo -old OLD.xml -new NEW.xml
```

---

## ABICC+dump (ABICC Usage #1 — abi-dumper / Binary Mode)

> This is what `abi-compliance-checker` calls **USAGE #1 (WITH ABI DUMPER)** in its docs.

### Overview

`abi-dumper` reads DWARF debug sections directly from the `.so` binary and produces
a `.dump` file. **No compiler is involved at any step.** ABICC then compares two dumps.

### How it works

```
libv1.so (with -g) ──► abi-dumper ──► ABI-1.dump ──┐
                                                     ├──► abi-compliance-checker ──► report
libv2.so (with -g) ──► abi-dumper ──► ABI-2.dump ──┘
```

### Requirements

| Requirement | Mandatory? | Notes |
|-------------|-----------|-------|
| Two `.so` compiled with `-g -Og` | ✅ | DWARF is the input — no debug info = no dump |
| `abi-dumper` | ✅ | `sudo apt-get install abi-dumper` |
| `abi-compliance-checker` | ✅ | |
| `universal-ctags` | ✅ | Required by abi-dumper |
| `vtable-dumper` | ✅ | For C++ vtable extraction |
| Compiler | ❌ **not needed** | abi-dumper reads binary DWARF, no compilation |
| Headers | ❌ optional | `abi-dumper -public-headers include/` filters to public API |

### What it catches (beyond Usage #2)

- ✅ Anonymous struct/union layouts (in DWARF but not expressible in headers)
- ✅ Types resolved by compiler flags/macros (DWARF = actual compiled result)
- ✅ Complex typedef chains to actual underlying types
- ✅ Bit-field layouts at bit-level precision
- ✅ `#pragma pack` effects
- ✅ Types from `.cpp` implementation files leaked into ABI

### What it misses

- ❌ Inline-only (header-only) API — never compiled into `.so`, no DWARF
- ❌ `noexcept` specifier (not stored in DWARF)
- ❌ ELF-only symbol visibility changes
- ❌ Requires `-g` build — not available for production stripped binaries

### Limitations

1. **Requires debug builds** — production `.so` files are stripped. This mode
   requires CI/staging debug builds.
2. **No compiler required, but debug info required** — the `.so` must be compiled
   with `-g -Og`. The compiler used (GCC, icpx, clang) does not matter for this mode —
   abi-dumper reads DWARF directly.

### Usage

```bash
sudo apt-get install abi-dumper abi-compliance-checker universal-ctags vtable-dumper

# Build with debug info (any compiler: gcc, icpx, clang)
g++ -shared -fPIC -g -Og -o libfoo_v1.so src_v1.cpp

abi-dumper libfoo_v1.so -o ABI-1.dump -lver 1.0 -public-headers include/
abi-dumper libfoo_v2.so -o ABI-2.dump -lver 2.0 -public-headers include/
abi-compliance-checker -lib libfoo -old ABI-1.dump -new ABI-2.dump
```

---

## Our Pipeline (Production Default)

`abicheck` runs **abidiff+headers + ABICC+headers (ABICC Usage #2)** by default:

```
abidiff+headers  ──────────────────────────────────────────► ELF-level report
ABICC+headers (ABICC Usage #2) (GCC compiles headers) ────────────────────► AST-level report
                                                              │
                                           combined verdict ◄─┘
                                  (worst-of: any break = breaking)
```

**Why not Usage #1 by default:**
- Production `.so` files are stripped (no `-g`) — abi-dumper cannot read DWARF
- Usage #2 works on production binaries and catches the C++ semantic cases (noexcept,
  templates, ODR) that abidiff misses
- Usage #1 is available as an optional mode when CI/staging provides debug builds

**Why two tools combined:**
- abidiff catches ELF-only symbol changes that ABICC+headers (ABICC Usage #2) misses
- ABICC+headers (ABICC Usage #2) catches noexcept/template/ODR that abidiff misses
- Together they cover the full ABI contract

---

## Tool Comparison Quick Reference

| ABI break type | abidiff+headers | ABICC+headers (ABICC Usage #2) | ABICC+dump (ABICC Usage #1) |
|---|:---:|:---:|:---:|
| Symbol removed | ✅ | ✅ | ✅ |
| Symbol added | ✅ | ✅ | ✅ |
| Param type change | ✅ | ✅ | ✅ |
| Struct layout change | ⚠️ DWARF | ✅ | ✅ |
| vtable change | ⚠️ DWARF | ✅ | ✅ |
| `noexcept` removed | ❌ | ✅ | ❌ |
| `inline` → non-inline | ❌ | ✅ | ❌ |
| Template ABI | ⚠️ DWARF | ✅ | ✅ |
| Dependency leak | ⚠️ DWARF | ✅ | ✅ |
| Anonymous types | ❌ | ❌ | ✅ |
| Macro-resolved types | ❌ | ❌ | ✅ |
| ELF-only visibility | ✅ | ❌ | ❌ |
| Needs compiler (GCC) | ❌ | ✅ GCC | ❌ |
| Needs debug build | ❌ | ❌ | ✅ |
