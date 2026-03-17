# Suppressions

`abicheck compare` and `abicheck compat` support YAML suppressions via `--suppress`.

Use suppressions to silence known/accepted changes while keeping detection enabled.

---

## File format

```yaml
version: 1
suppressions:
  - symbol: _ZN3Foo3barEv
    reason: "Known internal API drift"

  - symbol_pattern: "_ZN3Foo.*"
    change_kind: func_added
    label: internal

  - type_pattern: "dnnl_.*"
    change_kind: enum_member_added
    label: oneDNN-enum-growth

  - source_location: "*/internal/*"
    reason: "Do not gate on internal headers"

  - symbol_pattern: "_ZN4dnnl4impl.*"
    source_location: "*/dnnl.h"
    expires: 2026-12-31
    label: temporary
    reason: "Temporary waiver until downstream migration"
```

---

## Supported keys per rule

| Key | Type | Description |
|-----|------|-------------|
| `symbol` | string | Exact symbol match |
| `symbol_pattern` | regex string | Fullmatch regex against symbol |
| `type_pattern` | regex string | Fullmatch regex for type-level changes |
| `change_kind` | string | Restrict suppression to a specific change kind |
| `source_location` | glob string | `fnmatch`-style match against `change.source_location` |
| `label` | string | Optional grouping tag |
| `expires` | date/datetime | Expiry date; expired rule is ignored |
| `reason` | string | Human-readable rationale |

`symbol`, `symbol_pattern`, and `type_pattern` are mutually exclusive.
At least one selector is required (`symbol`/`symbol_pattern`/`type_pattern`/`source_location`).

---

## Matching semantics

Rules are evaluated with **AND** logic:

- if `source_location` is present, location must match;
- if `symbol` or `symbol_pattern` is present, symbol must match;
- if `type_pattern` is present, change must be a type-level change and pattern must match;
- if `change_kind` is present, kind must match.

So `source_location` does **not** bypass symbol/type selectors.

---

## Expiry behavior

- `expires` accepts ISO date (`2026-06-01`) and YAML datetime values.
- Datetime values are normalized to date for safe comparisons.
- Expired rules do not apply.

---

## CLI usage

```bash
abicheck compare old.so new.so \
  --old-header include/v1/ \
  --new-header include/v2/ \
  --suppress suppressions.yaml
```

For ABICC-compatible mode:

```bash
abicheck compat -lib libfoo.so -old old.dump -new new.dump --suppress suppressions.yaml
```
