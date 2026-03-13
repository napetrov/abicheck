# ABICC Compatibility Reference

`abicheck compat` is a drop-in replacement for `abi-compliance-checker`.
It accepts the same flags, produces the same exit codes, and reads the same XML descriptors.

## Quick start

```bash
# Before (ABICC):
abi-compliance-checker -lib libfoo -old old.xml -new new.xml -report-path r.html

# After (abicheck — identical):
abicheck compat -lib libfoo -old old.xml -new new.xml -report-path r.html
```

Exit codes match ABICC:

| Code | Meaning |
|------|---------|
| `0` | Compatible or no change |
| `1` | Breaking ABI change detected |
| `2` | Source-level break (`API_BREAK`) or error (descriptor parse failure, missing files) |

> **Note:** In `-strict` mode, `API_BREAK` is promoted to exit `1` (BREAKING).

## Full flag reference

### Core flags

| Flag | Alias(es) | Required | Description |
|------|-----------|:--------:|-------------|
| `-lib NAME` | `-l`, `-library` | ✅ | Library name (used in report and output path) |
| `-old PATH` | `-d1`, `-o` | ✅ | Path to old version XML descriptor or ABI dump |
| `-new PATH` | `-d2`, `-n` | ✅ | Path to new version XML descriptor or ABI dump |
| `-report-path PATH` | | | Output report path (default: `compat_reports/<lib>/<v1>_to_<v2>/report.html`) |
| `-report-format FMT` | | | Report format: `html` (default), `json`, `md` |
| `-bin-report-path PATH` | | | Separate binary-mode report output path |
| `-src-report-path PATH` | | | Separate source-mode report output path |

### Analysis mode flags

| Flag | Alias(es) | Description |
|------|-----------|-------------|
| `-source` | `-src`, `-api` | Source/API compatibility only — filters out ELF-level symbol metadata changes (SONAME, symbol binding, versioning) |
| `-binary` | `-bin`, `-abi` | Binary ABI mode (default behavior, explicit flag is a no-op) |
| `-s` | `-strict` | Strict mode: any change (COMPATIBLE or API_BREAK) is treated as BREAKING → exit 1 |
| `-warn-newsym` | | Treat new symbols (FUNC_ADDED, VAR_ADDED) as compatibility breaks → exit 1 |
| `-show-retval` | | Include return-value changes in the HTML report |
| `-headers-only` | | Header-only analysis mode (accepted; ELF/DWARF checks still run) |
| `-use-dumps` | | Interpret -old/-new as pre-built dumps (auto-detected by `.json` extension) |

### Output flags

| Flag | Alias(es) | Description |
|------|-----------|-------------|
| `-stdout` | | Print the report content to stdout in addition to writing to file |
| `-title NAME` | | Custom report title (wired to HTML `<title>` and `<h1>`) |
| `-component NAME` | | Component name shown in report (sets title to "ABI Report — LIB (COMPONENT)" if no -title) |
| `-limit-affected N` | | Maximum number of affected symbols shown per change kind |
| `-list-affected` | | Generate a separate `.affected.txt` file listing all affected symbols |
| `-q` | `-quiet` | Suppress console output (reports still written to file) |
| `-old-style` | | Legacy-style report layout (accepted for compatibility, no visual effect) |

### Version label overrides

| Flag | Alias(es) | Description |
|------|-----------|-------------|
| `-v1 NUM` | `-vnum1`, `-version1` | Override the version label for the old library |
| `-v2 NUM` | `-vnum2`, `-version2` | Override the version label for the new library |

These override what is in the `<version>` element of the XML descriptor.

### Symbol/type filtering

| Flag | Description |
|------|-------------|
| `-skip-symbols PATH` | File with newline-separated symbol names or patterns to suppress (blacklist) |
| `-skip-types PATH` | File with newline-separated type names or patterns to suppress (blacklist) |
| `-symbols-list PATH` | File with symbols to check (whitelist). Only changes on these symbols are reported. |
| `-types-list PATH` | File with types to check (whitelist). Only changes on these types are reported. |
| `-skip-internal-symbols PATTERN` | Regex pattern for internal symbols to skip |
| `-skip-internal-types PATTERN` | Regex pattern for internal types to skip |
| `-keep-cxx` | Include `_ZS*`, `_ZNS*`, `_ZNKS*` (C++ std) mangled symbols (accepted; abicheck includes all exported symbols by default) |
| `-keep-reserved` | Report changes in reserved fields (accepted; abicheck reports all field changes by default) |
| `--suppress PATH` | abicheck-native suppression YAML file (merged with all other filters) |

`-skip-symbols` / `-skip-types` file format:
```text
# Lines starting with # are comments
_Z3foov
_ZN3Foo3barEv
# Regex patterns (any of: * ? . [) are matched as full-symbol patterns:
_ZN.*detailEv
```

`-symbols-list` / `-types-list` file format (same syntax):
```text
# Only check these symbols — everything else is suppressed
_Z10public_apiv
_Z12another_funcv
```

### Header filtering

| Flag | Description |
|------|-------------|
| `-headers-list PATH` | File listing specific header files to include in analysis |
| `-header PATH` | Single header file to analyze |
| `-skip-headers PATH` | File listing headers to exclude (accepted, not yet wired) |

### Cross-compilation / toolchain flags

| Flag | Alias(es) | Description |
|------|-----------|-------------|
| `-gcc-path PATH` | `-cross-gcc` | Path to GCC/G++ cross-compiler binary (passed to castxml) |
| `-gcc-prefix PREFIX` | `-cross-prefix` | Cross-toolchain prefix, e.g. `aarch64-linux-gnu-` (builds compiler name as `<prefix>g++`) |
| `-gcc-options FLAGS` | | Extra compiler flags passed through to castxml |
| `-sysroot PATH` | | Alternative system root directory (passed as `--sysroot=` to castxml) |
| `-nostdinc` | | Do not search standard system include paths |
| `-lang LANG` | | Force language: `C` or `C++` (affects header extension and castxml mode) |
| `-arch ARCH` | | Target architecture (informational, recorded in dump metadata) |

### Relpath macros

| Flag | Description |
|------|-------------|
| `-relpath PATH` | Replace `{RELPATH}` macros in both old and new descriptor paths |
| `-relpath1 PATH` | Replace `{RELPATH}` macros in old descriptor paths only |
| `-relpath2 PATH` | Replace `{RELPATH}` macros in new descriptor paths only |

Relpath substitution is an ABICC feature for portable XML descriptors:
```xml
<version>2025.0</version>
<headers>{RELPATH}/include/</headers>
<libs>{RELPATH}/lib/libfoo.so</libs>
```

```bash
abicheck compat -lib libfoo -old desc.xml -new desc.xml \
  -relpath1 /builds/v1 -relpath2 /builds/v2
```

### Logging flags

| Flag | Description |
|------|-------------|
| `-log-path PATH` | Redirect log output to file |
| `-log1-path PATH` | Separate log path for old library analysis |
| `-log2-path PATH` | Separate log path for new library analysis |
| `-logging-mode MODE` | Logging mode: `w` (overwrite, default), `a` (append), `n` (none) |

### Input filtering flags

| Flag | Description |
|------|-------------|
| `-d` / `-f` / `-filter PATH` | Path to XML descriptor with skip rules (accepted for compatibility) |
| `-p` / `-params PATH` | Path to parameters file (accepted for compatibility) |
| `-app` / `-application PATH` | Application binary for portability checking (accepted for compatibility) |

### Stub flags (accepted for ABICC CLI compatibility, no effect)

These flags are accepted silently to ensure drop-in compatibility with ABICC
CI scripts. They produce a warning when used but do not change behavior:

| Flag | Description |
|------|-------------|
| `-mingw-compatible` | MinGW ABI mode |
| `-cxx-incompatible` / `-cpp-incompatible` | C++ incompatibility mode |
| `-cpp-compatible` | C++ compatibility mode |
| `-static` / `-static-libs` | Static library analysis |
| `-ext` / `-extended` | Extended analysis mode |
| `-quick` | Quick analysis mode |
| `-force` | Force analysis |
| `-check` | Dump validity check |
| `-extra-info DIR` | Extra analysis output directory |
| `-extra-dump` | Extended dump |
| `-sort` | Sort dump output |
| `-xml` | XML dump format |
| `-skip-typedef-uncover` | Skip typedef uncovering |
| `-check-private-abi` | Check private ABI |
| `-skip-unidentified` | Skip unidentified headers |
| `-tolerance LEVEL` | Header parsing tolerance |
| `-tolerant` | Enable all tolerance levels |
| `-disable-constants-check` | Skip constant checking |
| `-skip-added-constants` | Skip new constants |
| `-skip-removed-constants` | Skip removed constants |
| `-count-symbols PATH` | Count symbols in library |
| `-count-all-symbols PATH` | Count all symbols in library |

## ABI dump workflow

abicheck supports a two-stage workflow: dump first, compare later. This is
useful for CI pipelines that build versions at different times.

### Creating dumps

```bash
# Create an ABI dump from an XML descriptor:
abicheck compat-dump -lib libfoo -dump v1.xml

# With explicit output path:
abicheck compat-dump -lib libfoo -dump v1.xml -dump-path libfoo-v1.json

# Override version label:
abicheck compat-dump -lib libfoo -dump v1.xml -vnum 2025.1

# Cross-compilation:
abicheck compat-dump -lib libfoo -dump v1.xml -gcc-prefix aarch64-linux-gnu-

# With sysroot:
abicheck compat-dump -lib libfoo -dump v1.xml -sysroot /opt/cross/sysroot

# Force C language:
abicheck compat-dump -lib libfoo -dump v1.xml -lang C
```

Default output: `abi_dumps/<lib>/<version>/dump.json`

### compat-dump flags

| Flag | Alias(es) | Required | Description |
|------|-----------|:--------:|-------------|
| `-lib NAME` | `-l`, `-library` | ✅ | Library name |
| `-dump PATH` | | ✅ | Path to ABICC XML descriptor |
| `-dump-path PATH` | | | Output dump file path |
| `-dump-format FMT` | | | Only `json` supported |
| `-vnum VERSION` | | | Override version label |
| `-gcc-path` | `-cross-gcc` | | Cross-compiler path |
| `-gcc-prefix` | `-cross-prefix` | | Cross-toolchain prefix |
| `-gcc-options` | | | Extra compiler flags |
| `-sysroot PATH` | | | Alternative system root |
| `-nostdinc` | | | No standard includes |
| `-lang LANG` | | | Force C or C++ |
| `-arch ARCH` | | | Target architecture |
| `-relpath PATH` | | | Relpath macro substitution |
| `-q` | `-quiet` | | Suppress console output |

### Comparing dumps

JSON dumps can be passed directly to `compat` (auto-detected by `.json` extension)
or to the native `compare` command:

```bash
# Via compat mode (ABICC-style exit codes):
abicheck compat -lib libfoo -old libfoo-v1.json -new libfoo-v2.json

# Via native compare (abicheck exit codes):
abicheck compare libfoo-v1.json libfoo-v2.json --format html -o report.html
```

### Dump format

abicheck supports:

- native **JSON** dumps, and
- minimal ABICC Perl `Data::Dumper` (`ABI.dump`) input for migration workflows.

ABICC XML dump variants (`<ABI_dump...>` / `<abi_dump...>`) are still unsupported.

```bash
# ABICC Perl dump (default abi-dumper output):
abicheck compat -lib libfoo -old old.ABI.dump -new new.ABI.dump  # ✅

# ABICC XML dump variant:
abicheck compat -lib libfoo -old old.xml_dump -new new.xml_dump  # ❌ not supported

# Descriptor-based fallback:
abicheck compat-dump -lib libfoo -dump old_descriptor.xml -dump-path old.json
abicheck compat-dump -lib libfoo -dump new_descriptor.xml -dump-path new.json
abicheck compat -lib libfoo -old old.json -new new.json  # ✅
```


## `-source` mode: what gets filtered

In `-source` mode, ELF/binary-only changes are removed from the report and verdict:

**Filtered out (binary-only):**
- `SONAME_CHANGED`
- `NEEDED_ADDED` / `NEEDED_REMOVED`
- `RPATH_CHANGED` / `RUNPATH_CHANGED`
- `SYMBOL_BINDING_CHANGED` / `SYMBOL_BINDING_STRENGTHENED`
- `SYMBOL_TYPE_CHANGED` / `SYMBOL_SIZE_CHANGED`
- `IFUNC_INTRODUCED` / `IFUNC_REMOVED`
- `COMMON_SYMBOL_RISK`
- `SYMBOL_VERSION_DEFINED_REMOVED` / `SYMBOL_VERSION_REQUIRED_*`
- `DWARF_INFO_MISSING`
- `TOOLCHAIN_FLAG_DRIFT`

**Retained (source/API breaks):**
- `FUNC_PARAMS_CHANGED`, `FUNC_RETURN_CHANGED`
- `FUNC_NOEXCEPT_ADDED` / `FUNC_NOEXCEPT_REMOVED`
- `FUNC_DELETED`
- `TYPE_FIELD_REMOVED` / `TYPE_FIELD_TYPE_CHANGED`
- `TYPE_REMOVED` / `TYPE_BECAME_OPAQUE`
- `TYPEDEF_REMOVED` / `TYPEDEF_BASE_CHANGED`
- `ENUM_MEMBER_REMOVED` / `ENUM_MEMBER_VALUE_CHANGED` / `ENUM_MEMBER_ADDED`

## `-strict` mode

Without `-strict`:
- `COMPATIBLE` changes → exit 0
- `API_BREAK` → exit 2
- `BREAKING` → exit 1

With `-strict`:
- `NO_CHANGE` → exit 0
- Anything else (`COMPATIBLE`, `API_BREAK`, `BREAKING`) → exit 1

Matches ABICC's `-strict` semantics: any deviation from the old ABI is an error.

## `-warn-newsym` mode

Without `-warn-newsym`:
- New symbols (`FUNC_ADDED`, `VAR_ADDED`) are COMPATIBLE → exit 0

With `-warn-newsym`:
- New symbols promote verdict to BREAKING → exit 1

Useful for strict CI pipelines that need to flag any ABI surface change.

## XML descriptor format

Same format as ABICC:

```xml
<version>2025.0</version>
<headers>/path/to/include/</headers>
<libs>/path/to/libfoo.so</libs>
```

Multiple `<headers>` and `<libs>` entries are supported. If multiple `<libs>` are
provided, only the first is used (with a warning).

The `{RELPATH}` macro is supported for portable descriptors (see Relpath macros above).

## Detector coverage vs ABICC

abicheck compat mode uses **all abicheck detectors** — it does not emulate ABICC's
blind spots. This means abicheck may report issues that ABICC would miss:

| Scenario | ABICC | abicheck compat |
|----------|:-----:|:---------------:|
| Enum value changed | ✅ | ✅ |
| Base class position reordered | ✅ | ✅ |
| Function `= delete` added | ✅ | ✅ |
| Global var became const | ❌ | ✅ |
| Type became opaque | ✅ | ✅ |
| C++ templates (timeout) | ⏱️ | ✅ |
| ELF symbol metadata | ❌ | ✅ |

Full coverage comparison: see [gap_report.md](gap_report.md).

## ABICC flag coverage status

### Supported flags (functional)

| ABICC Flag | Status |
|---|---|
| `-lib` / `-l` / `-library` | ✅ Full parity |
| `-old` / `-d1` / `-o` | ✅ Full parity |
| `-new` / `-d2` / `-n` | ✅ Full parity |
| `-v1` / `-vnum1` / `-version1` | ✅ Full parity |
| `-v2` / `-vnum2` / `-version2` | ✅ Full parity |
| `-report-path` | ✅ Full parity |
| `-report-format` | ✅ `html/json/md` (ABICC: `htm/xml`) |
| `-bin-report-path` | ✅ Separate binary report |
| `-src-report-path` | ✅ Separate source report |
| `-binary` / `-bin` / `-abi` | ✅ Full parity |
| `-source` / `-src` / `-api` | ✅ Full parity |
| `-s` / `-strict` | ✅ Full parity |
| `-stdout` | ✅ Full parity |
| `-title` | ✅ Wired to HTML output |
| `-component` | ✅ Sets report title |
| `-skip-symbols` | ✅ Full parity |
| `-skip-types` | ✅ Full parity |
| `-symbols-list` | ✅ Whitelist filtering |
| `-types-list` | ✅ Whitelist filtering |
| `-skip-internal-symbols` | ✅ Regex pattern |
| `-skip-internal-types` | ✅ Regex pattern |
| `-keep-cxx` | ✅ Accepted (all symbols included by default) |
| `-keep-reserved` | ✅ Accepted (all fields reported by default) |
| `-warn-newsym` | ✅ Full parity |
| `-limit-affected` | ✅ Full parity |
| `-list-affected` | ✅ Generates `.affected.txt` |
| `-q` / `-quiet` | ✅ Suppress console output |
| `-dump` (via `compat-dump`) | ✅ JSON format |
| `-dump-path` (via `compat-dump`) | ✅ Full parity |
| `-dump-format` (via `compat-dump`) | ✅ JSON only (with warning) |
| `-vnum` (via `compat-dump`) | ✅ Version override for dumps |
| `-gcc-path` / `-cross-gcc` | ✅ Passed to castxml |
| `-gcc-prefix` / `-cross-prefix` | ✅ Builds cross-compiler name |
| `-gcc-options` | ✅ Extra compiler flags |
| `-sysroot` | ✅ Passed as `--sysroot=` to castxml |
| `-nostdinc` | ✅ Suppresses standard includes |
| `-lang` | ✅ Forces C or C++ mode |
| `-arch` | ✅ Informational |
| `-relpath` / `-relpath1` / `-relpath2` | ✅ `{RELPATH}` macro substitution |
| `-headers-list` | ✅ Additional header files |
| `-header` | ✅ Single header file |
| `-log-path` / `-log1-path` / `-log2-path` | ✅ Log redirection |
| `-logging-mode` | ✅ Append/overwrite control |
| `-headers-only` | ✅ Accepted (ELF checks still run) |
| `-show-retval` | ✅ Accepted |
| `-old-style` | ✅ Accepted (no visual effect) |
| `-use-dumps` | ✅ Accepted (auto-detected) |
| `-filter` / `-d` / `-f` | ✅ Accepted for compatibility |
| `-params` / `-p` | ✅ Accepted for compatibility |
| `-app` / `-application` | ✅ Accepted for compatibility |

### Stub flags (accepted, no functional effect)

| ABICC Flag | Status |
|---|---|
| `-mingw-compatible` | ✅ Accepted with warning |
| `-cxx-incompatible` / `-cpp-incompatible` | ✅ Accepted with warning |
| `-cpp-compatible` | ✅ Accepted with warning |
| `-static` / `-static-libs` | ✅ Accepted with warning |
| `-ext` / `-extended` | ✅ Accepted with warning |
| `-quick` | ✅ Accepted with warning |
| `-force` | ✅ Accepted with warning |
| `-check` | ✅ Accepted with warning |
| `-extra-info` | ✅ Accepted with warning |
| `-extra-dump` | ✅ Accepted with warning |
| `-sort` | ✅ Accepted with warning |
| `-xml` | ✅ Accepted with warning |
| `-skip-typedef-uncover` | ✅ Accepted with warning |
| `-check-private-abi` | ✅ Accepted with warning |
| `-skip-unidentified` | ✅ Accepted with warning |
| `-tolerance` / `-tolerant` | ✅ Accepted with warning |
| `-disable-constants-check` | ✅ Accepted with warning |
| `-skip-added-constants` | ✅ Accepted with warning |
| `-skip-removed-constants` | ✅ Accepted with warning |
| `-count-symbols` / `-count-all-symbols` | ✅ Accepted with warning |

## CI cross-validation

To validate abicheck produces correct results for your CI pipeline:

```bash
# 1. Run both tools on the same inputs
abi-compliance-checker -lib libfoo -old old.xml -new new.xml; ABICC_EXIT=$?
abicheck compat -lib libfoo -old old.xml -new new.xml; ABICHECK_EXIT=$?

# 2. Compare exit codes
test $ABICC_EXIT -eq $ABICHECK_EXIT && echo "PASS" || echo "FAIL: $ABICC_EXIT vs $ABICHECK_EXIT"
```

## Examples

```bash
# Basic comparison
abicheck compat -lib mylib -old v1.xml -new v2.xml

# Strict: any change fails CI
abicheck compat -lib mylib -old v1.xml -new v2.xml -s

# Source/API compat only (ignore ELF metadata changes)
abicheck compat -lib mylib -old v1.xml -new v2.xml -source

# Override version labels
abicheck compat -lib mylib -old v1.xml -new v2.xml -v1 2025.0 -v2 2025.1

# Skip known-breaking symbols
echo "_Z14legacy_internalv" > skip.txt
abicheck compat -lib mylib -old v1.xml -new v2.xml -skip-symbols skip.txt

# Whitelist: only check public API symbols
abicheck compat -lib mylib -old v1.xml -new v2.xml -symbols-list public_api.txt

# Skip internal symbols by regex
abicheck compat -lib mylib -old v1.xml -new v2.xml -skip-internal-symbols "_ZN.*detail.*"

# Treat new symbols as breaks
abicheck compat -lib mylib -old v1.xml -new v2.xml -warn-newsym

# Limit output + affected list
abicheck compat -lib mylib -old v1.xml -new v2.xml -limit-affected 5 -list-affected

# Print report to stdout (for CI log capture)
abicheck compat -lib mylib -old v1.xml -new v2.xml -stdout

# Quiet mode (report written, no console output)
abicheck compat -lib mylib -old v1.xml -new v2.xml -q

# JSON output
abicheck compat -lib mylib -old v1.xml -new v2.xml -report-format json

# Cross-compilation
abicheck compat -lib mylib -old v1.xml -new v2.xml -gcc-prefix aarch64-linux-gnu- -sysroot /opt/sysroot

# Relpath macros (portable descriptors)
abicheck compat -lib mylib -old desc.xml -new desc.xml -relpath1 /builds/v1 -relpath2 /builds/v2

# Split binary + source reports
abicheck compat -lib mylib -old v1.xml -new v2.xml -bin-report-path bin.html -src-report-path src.html

# Log to file
abicheck compat -lib mylib -old v1.xml -new v2.xml -log-path analysis.log

# Two-stage workflow: dump then compare
abicheck compat-dump -lib mylib -dump v1.xml
abicheck compat-dump -lib mylib -dump v2.xml
abicheck compat -lib mylib -old abi_dumps/mylib/1.0/dump.json -new abi_dumps/mylib/2.0/dump.json

# Cross-compiled dump
abicheck compat-dump -lib mylib -dump v1.xml -gcc-prefix aarch64-linux-gnu- -sysroot /opt/sysroot
```
