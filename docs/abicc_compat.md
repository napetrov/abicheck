# ABICC Compatibility Reference

`abicheck compat` is a drop-in replacement for `abi-compliance-checker`.
It accepts the same flags, produces the same exit codes, and reads the same XML descriptors.

## Quick start

```bash
# Before (ABICC):
abi-compliance-checker -lib libdnnl -old old.xml -new new.xml -report-path r.html

# After (abicheck — identical):
abicheck compat -lib libdnnl -old old.xml -new new.xml -report-path r.html
```

Exit codes match ABICC:

| Code | Meaning |
|------|---------|
| `0` | Compatible or no change |
| `1` | Breaking ABI change detected |
| `2` | Source-level break (`SOURCE_BREAK`) or error (descriptor parse failure, missing files) |

> **Note:** In `-strict` mode, `SOURCE_BREAK` is promoted to exit `1` (BREAKING).

## Full flag reference

### Core flags

| Flag | Alias(es) | Required | Description |
|------|-----------|:--------:|-------------|
| `-lib NAME` | `-l`, `-library` | ✅ | Library name (used in report and output path) |
| `-old PATH` | `-d1` | ✅ | Path to old version XML descriptor or ABI dump |
| `-new PATH` | `-d2` | ✅ | Path to new version XML descriptor or ABI dump |
| `-report-path PATH` | | | Output report path (default: `compat_reports/<lib>/<v1>_to_<v2>/report.html`) |
| `-report-format FMT` | | | Report format: `html` (default), `json`, `md` |

### Analysis mode flags

| Flag | Alias(es) | Description |
|------|-----------|-------------|
| `-source` | `-src`, `-api` | Source/API compatibility only — filters out ELF-level symbol metadata changes (SONAME, symbol binding, versioning) |
| `-binary` | `-bin`, `-abi` | Binary ABI mode (default behavior, explicit flag is a no-op) |
| `-s` | `-strict` | Strict mode: any change (COMPATIBLE or SOURCE_BREAK) is treated as BREAKING → exit 1 |
| `-warn-newsym` | | Treat new symbols (FUNC_ADDED, VAR_ADDED) as compatibility breaks → exit 1 |
| `-show-retval` | | Include return-value changes in the HTML report |

### Output flags

| Flag | Description |
|------|-------------|
| `-stdout` | Print the report content to stdout in addition to writing to file |
| `-title NAME` | Custom report title (wired to HTML `<title>` and `<h1>`) |
| `-component NAME` | Component name shown in report (sets title to "ABI Report — LIB (COMPONENT)" if no -title) |
| `-limit-affected N` | Maximum number of affected symbols shown per change kind |
| `-list-affected` | Generate a separate `.affected.txt` file listing all affected symbols |
| `-q` | `-quiet` | Suppress console output (reports still written to file) |

### Version label overrides

| Flag | Alias | Description |
|------|-------|-------------|
| `-v1 NUM` | `-vnum1` | Override the version label for the old library |
| `-v2 NUM` | `-vnum2` | Override the version label for the new library |

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
| `--suppress PATH` | abicheck-native suppression YAML file (merged with all other filters) |

`-skip-symbols` / `-skip-types` file format:
```text
# Lines starting with # are comments
_Z3foov
_ZN3Foo3barEv
# Regex patterns (any of: * ? . [) are matched as full-symbol patterns:
_ZN.*intelEv
```

`-symbols-list` / `-types-list` file format (same syntax):
```text
# Only check these symbols — everything else is suppressed
_Z10public_apiv
_Z12another_funcv
```

### Placeholder flags (accepted, not yet implemented)

| Flag | Status |
|------|--------|
| `-headers-only` | Accepted; reserved for future header-only analysis mode. ELF/DWARF checks still run. |
| `-skip-headers PATH` | Accepted; reserved for future header-skip support. |

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
```

Default output: `abi_dumps/<lib>/<version>/dump.json`

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

abicheck uses its own **JSON dump format** — it does not use ABICC's Perl
`Data::Dumper` or XML dump formats. If you have existing ABICC dumps, you need
to re-create them from the original XML descriptors:

```bash
# ABICC dump → not supported:
abicheck compat -old old.dump -new new.dump  # ❌ Error with migration guidance

# Re-create from descriptor:
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
- `SOURCE_BREAK` → exit 2
- `BREAKING` → exit 1

With `-strict`:
- `NO_CHANGE` → exit 0
- Anything else (`COMPATIBLE`, `SOURCE_BREAK`, `BREAKING`) → exit 1

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

## Detector coverage vs ABICC

abicheck compat mode uses **all abicheck detectors** — it does not emulate ABICC's
blind spots. This means abicheck may report issues that ABICC would miss:

| Scenario | ABICC | abicheck compat |
|----------|:-----:|:---------------:|
| Enum value changed | ✅ | ✅ |
| Base class position reordered | ✅ | ✅ |
| Function `= delete` added | ✅ | ✅ (Sprint 2) |
| Global var became const | ❌ | ✅ (Sprint 2) |
| Type became opaque | ✅ | ✅ (Sprint 2) |
| C++ templates (timeout) | ⏱️ | ✅ |
| ELF symbol metadata | ❌ | ✅ |

Full coverage comparison: see [gap_report.md](gap_report.md).

## ABICC flag coverage status

### Supported flags (functional)

| ABICC Flag | Status |
|---|---|
| `-lib` / `-l` / `-library` | ✅ Full parity |
| `-old` / `-d1` | ✅ Full parity |
| `-new` / `-d2` | ✅ Full parity |
| `-v1` / `-vnum1` | ✅ Full parity |
| `-v2` / `-vnum2` | ✅ Full parity |
| `-report-path` | ✅ Full parity |
| `-report-format` | ✅ `html/json/md` (ABICC: `htm/xml`) |
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
| `-warn-newsym` | ✅ Full parity |
| `-limit-affected` | ✅ Full parity |
| `-list-affected` | ✅ Generates `.affected.txt` |
| `-q` / `-quiet` | ✅ Suppress console output |
| `-dump` (via `compat-dump`) | ✅ JSON format (not ABICC Perl/XML) |
| `-dump-path` (via `compat-dump`) | ✅ Full parity |
| `-vnum` (via `compat-dump`) | ✅ Version override for dumps |

### Not yet implemented

| ABICC Flag | Priority | Notes |
|---|---|---|
| `-headers-only` | P1 | Accepted, not wired |
| `-skip-headers` | P1 | Accepted, not wired |
| `-show-retval` | P1 | Accepted, not wired |
| `-bin-report-path` / `-src-report-path` | P2 | Separate binary/source reports |
| `-dump-format` | P2 | Only JSON supported (not ABICC Perl/XML) |
| `-gcc-path` / `-cross-gcc` | P2 | Cross-compilation |
| `-gcc-prefix` / `-cross-prefix` | P2 | Toolchain prefix |
| `-sysroot` | P2 | Alternative sysroot |
| `-lang` | P2 | Force C/C++ |
| `-static` / `-static-libs` | P2 | Static library analysis |
| `-ext` / `-extended` | P3 | Check all types |
| `-keep-cxx` | P3 | Include std mangled syms |
| `-old-style` | P3 | Legacy report layout |
| `-tolerance` / `-tolerant` | P3 | Compilation heuristics |

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

# Two-stage workflow: dump then compare
abicheck compat-dump -lib mylib -dump v1.xml
abicheck compat-dump -lib mylib -dump v2.xml
abicheck compat -lib mylib -old abi_dumps/mylib/1.0/dump.json -new abi_dumps/mylib/2.0/dump.json
```
