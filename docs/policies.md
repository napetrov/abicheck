# Policy Profiles

`abicheck compare` and `abicheck compat` support a `--policy` flag that controls
how changes are classified into verdict levels.

## Usage

```bash
abicheck compare old.json new.json --policy strict_abi   # default
abicheck compare old.json new.json --policy sdk_vendor
abicheck compare old.json new.json --policy plugin_abi
```

## Available Profiles

### `strict_abi` (default)

Full strictness — every detected ABI change is classified at its maximum severity.

| Verdict | Meaning |
|---------|---------|
| `BREAKING` | Binary ABI break — old callers will crash or misbehave |
| `API_BREAK` | Source-level break — recompile required, but binary may still work |
| `COMPATIBLE` | Safe addition or informational |
| `NO_CHANGE` | No differences found |

Use for: shared libraries, system libraries, public SDKs with strict compatibility guarantees.

---

### `sdk_vendor`

Permissive profile for SDK / vendor libraries. Source-level-only changes
(renames, access changes) are downgraded from `API_BREAK` to `COMPATIBLE`
since SDK consumers typically use stable binary interfaces, not source-level names.

**Downgraded to `COMPATIBLE` under `sdk_vendor`:**

| Change Kind | Description |
|-------------|-------------|
| `enum_member_renamed` | Enum member name changed (value unchanged) |
| `field_renamed` | Struct/class field name changed |
| `param_renamed` | Function parameter name changed |
| `method_access_changed` | Method access level changed |
| `field_access_changed` | Field access level changed |
| `source_level_kind_changed` | `struct` ↔ `class` keyword (binary-identical) |
| `removed_const_overload` | const overload removed |
| `param_default_value_removed` | Default argument removed |
| `param_default_value_changed` | Default argument value changed |

All `BREAKING` kinds remain `BREAKING` — this profile does not suppress binary breaks.

Use for: vendor SDKs, optional library extensions, plugin APIs where source compat is not required.

---

### `plugin_abi`

Relaxed profile for plugins that are built from the **same toolchain** as the host
at the same time. Calling-convention signals are downgraded to `COMPATIBLE` since
they are controlled by the build system rather than the library ABI contract.

**Downgraded to `COMPATIBLE` under `plugin_abi`:**

| Change Kind | Description |
|-------------|-------------|
| `calling_convention_changed` | DWARF DW_AT_calling_convention drift |
| `frame_register_changed` | CFA/frame-pointer register changed (.eh_frame) |
| `value_abi_trait_changed` | DWARF triviality heuristic (pass-by-reg vs pointer) |
| `toolchain_flag_drift` | -fshort-enums/-fpack-struct ABI flag drift |

All `BREAKING` kinds that are not calling-convention-related remain `BREAKING`.

Use for: dynamically-loaded plugins, JNI/Python extension modules, hot-reload scenarios
where the plugin and host are always rebuilt together.

---

## Exit Codes

Exit codes are the same for all policies — only the verdict changes:

| Exit Code | Verdict |
|-----------|---------|
| `0` | `NO_CHANGE` or `COMPATIBLE` |
| `2` | `API_BREAK` (source-level break) |
| `4` | `BREAKING` (binary ABI break) |

---

## Extending Policies

Policy profiles are defined in `abicheck/checker_policy.py`:
- `SDK_VENDOR_COMPAT_KINDS` — kinds downgraded to COMPATIBLE under `sdk_vendor`
- `PLUGIN_ABI_DOWNGRADED_KINDS` — kinds downgraded to COMPATIBLE under `plugin_abi`

To add a custom profile, extend `compute_verdict()` with a new `elif policy == "..."` branch.
