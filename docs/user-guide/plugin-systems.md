# Plugin Systems (host ↔ plugin)

Plugin architectures have a **two-sided ABI contract** that neither `compare`
nor `appcompat` fully captures on its own:

- A **host** `dlopen`s each plugin and resolves a fixed set of **entry-point
  symbols** (`dlsym("plugin_init")`, …). If a plugin upgrade drops or changes
  one of those, the host fails to load it — *regardless* of the plugin's
  library-wide verdict.
- The host and plugin are usually built **in-process**, so some changes that
  `strict_abi` flags (e.g. calling-convention nuances) are not relevant.

`abicheck` addresses both sides:

| Concern | Tool |
|---------|------|
| Does plugin **v2** still satisfy the host's required entrypoints? | `abicheck plugin-check` |
| Downgrade in-process-only ABI noise to the right severity | `--policy plugin_abi` |

---

## `plugin-check` — the host's load contract

Give the old and new plugin (binary **or** JSON snapshot) plus the host's
required entrypoints, and `plugin-check` reports whether the new plugin still
satisfies the host — the plugin-load mirror of `appcompat`.

```bash
# Entrypoints listed inline:
abicheck plugin-check plugin.v1.so plugin.v2.so -r plugin_init -r plugin_run

# …or from a manifest file (one symbol per line, '#' comments allowed):
abicheck plugin-check plugin.v1.so plugin.v2.so --host-contract host.syms
```

A `host.syms` manifest is just the symbols the host resolves:

```text
plugin_init
plugin_run     # core entrypoint
plugin_shutdown
```

### What it reports

- **Missing entrypoints** — required symbols the new plugin no longer exports
  (a hard load break).
- **Incompatible changes affecting the host** — diff changes that touch a
  required entrypoint (e.g. a signature change), scoped exactly like
  `appcompat` scopes changes to an application's used symbols.
- A host-scoped **verdict** and entrypoint **coverage** percentage.

A library-wide `BREAKING` drop of a symbol the host never resolves leaves the
host **COMPATIBLE** — that consumer-scoped distinction is the whole point.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | `COMPATIBLE` — the new plugin still satisfies the host |
| `2` | `API_BREAK` — source-level break affecting a required entrypoint |
| `4` | `BREAKING` — a required entrypoint was dropped or is ABI-incompatible |

---

## `plugin_abi` policy

For in-process host/plugin builds, use the `plugin_abi` policy (the default for
`plugin-check`) so calling-convention–style findings that do not matter for a
co-built host/plugin pair are weighted appropriately:

```bash
abicheck compare plugin.v1.so plugin.v2.so --policy plugin_abi
abicheck plugin-check plugin.v1.so plugin.v2.so -r plugin_init --policy plugin_abi
```

See [Policy Profiles](policies.md) for the full policy model.

---

## Python API

```python
from abicheck.appcompat import check_plugin_host_contract
from abicheck.service import resolve_input

old = resolve_input("plugin.v1.so")
new = resolve_input("plugin.v2.so")
result = check_plugin_host_contract(old, new, {"plugin_init", "plugin_run"})

print(result.verdict, result.missing_entrypoints, result.coverage)
```
