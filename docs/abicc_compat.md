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
| `2` | Error (descriptor parse failure, missing files) |

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
| `-show-retval` | | Include return-value changes in the HTML report |

### Output flags

| Flag | Description |
|------|-------------|
| `-stdout` | Print the report content to stdout in addition to writing to file |
| `-title NAME` | Custom report title _(not yet wired to HTML output — TODO)_ |

### Version label overrides

| Flag | Alias | Description |
|------|-------|-------------|
| `-v1 NUM` | `-vnum1` | Override the version label for the old library |
| `-v2 NUM` | `-vnum2` | Override the version label for the new library |

These override what is in the `<version>` element of the XML descriptor.

### Symbol/type filtering

| Flag | Description |
|------|-------------|
| `-skip-symbols PATH` | File with newline-separated symbol names or patterns to suppress |
| `-skip-types PATH` | File with newline-separated type names or patterns to suppress |
| `--suppress PATH` | abicheck-native suppression YAML file (merged with `-skip-symbols`/`-skip-types`) |

`-skip-symbols` / `-skip-types` file format:
```
# Lines starting with # are comments
_Z3foov
_ZN3Foo3barEv
# Regex patterns (any of: * ? . [) are matched as full-symbol patterns:
_ZN.*intelEv
```

### Placeholder flags (accepted, not yet implemented)

| Flag | Status |
|------|--------|
| `-headers-only` | Accepted; reserved for future header-only analysis mode. ELF/DWARF checks still run. |
| `-skip-headers PATH` | Accepted; reserved for future header-skip support. |

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

# Print report to stdout (for CI log capture)
abicheck compat -lib mylib -old v1.xml -new v2.xml -stdout

# JSON output
abicheck compat -lib mylib -old v1.xml -new v2.xml -report-format json
```
