# Architecture

## Scope (v0.1)

abicheck v0.1 supports:

- **Platform:** Linux only
- **Binary format:** ELF (`.so`)
- **Debug metadata:** DWARF (optional but used for advanced checks)

Not supported in v0.1:
- Windows PE/COFF
- macOS Mach-O

---

## Pipeline

abicheck uses a pragmatic 3-layer comparison model:

1. **Header AST (castxml)**
   - Public API extraction from headers
   - Function signatures, classes, fields, typedefs, enums

2. **ELF metadata (pyelftools + readelf parity)**
   - Exported symbol table (`.dynsym` priority)
   - SONAME, NEEDED, symbol binding/type/version drift

3. **DWARF metadata (optional, advanced checks)**
   - Struct layout and calling convention details
   - Frame register / CFA convention changes

Result: one `DiffResult` with classified changes and verdict.

---

## Main modules

- `abicheck/cli.py` — CLI entrypoint (`dump`, `compare`, `compat`, `compat-dump`)
- `abicheck/dumper.py` — snapshot generation from `.so` + headers
- `abicheck/checker.py` — diff orchestration and change collection
- `abicheck/checker_policy.py` — `ChangeKind`, built-in policies, verdict logic
- `abicheck/policy_file.py` — YAML policy overrides (`--policy-file`)
- `abicheck/reporter.py` / `html_report.py` / `xml_report.py` — output formats
- `abicheck/suppression.py` — suppression rules and filtering

---

## Policy model

Built-ins:
- `strict_abi` (default)
- `sdk_vendor`
- `plugin_abi`

Custom:
- `--policy-file <yaml>` with per-kind `break|warn|ignore` overrides

Single source of truth:
- `policy_kind_sets()` in `checker_policy.py`

---

## Error model

Public exceptions live in:
- `abicheck/errors.py`

Older `abicheck.core.*` architecture modules were removed from active runtime in v0.1.
