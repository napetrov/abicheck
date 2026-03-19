# MCP Server (Agent Integration)

abicheck includes an MCP ([Model Context Protocol](https://modelcontextprotocol.io/)) server that exposes ABI checking as structured tools for AI agents — Claude Code, Cursor, VS Code Copilot, OpenAI Agents, and any other MCP-compatible client.

## Install

```bash
pip install "abicheck[mcp]"
```

Or with conda:

```bash
conda install abicheck
pip install "mcp[cli]>=1.2.0"
```

> The `mcp` dependency is optional. The base `pip install abicheck` does not pull it in.

## Configure

### Claude Desktop / Claude Code

Add to `~/.claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "abicheck": {
      "command": "abicheck-mcp"
    }
  }
}
```

### Cursor / VS Code

Add to `.cursor/mcp.json` or VS Code MCP settings:

```json
{
  "mcpServers": {
    "abicheck": {
      "command": "abicheck-mcp"
    }
  }
}
```

### Without installing (via uv)

```json
{
  "mcpServers": {
    "abicheck": {
      "command": "uv",
      "args": ["--directory", "/path/to/abicheck", "run", "abicheck-mcp"]
    }
  }
}
```

## Tools

The MCP server exposes four tools. All return structured JSON.

### `abi_compare` — Compare two ABI surfaces

The primary tool. Diffs two library versions and reports breaking changes.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `old_input` | string | yes | Path to old .so/.dll/.dylib or JSON snapshot |
| `new_input` | string | yes | Path to new .so/.dll/.dylib or JSON snapshot |
| `headers` | string[] | no | Header files for both sides |
| `old_headers` | string[] | no | Headers for old side only |
| `new_headers` | string[] | no | Headers for new side only |
| `include_dirs` | string[] | no | Include directories for C/C++ parser |
| `language` | string | no | `"c++"` (default) or `"c"` |
| `policy` | string | no | `"strict_abi"` (default), `"sdk_vendor"`, or `"plugin_abi"` |
| `policy_file` | string | no | Path to custom YAML policy file |
| `suppression_file` | string | no | Path to YAML suppression file |
| `output_format` | string | no | Report format: `"json"` (default), `"markdown"`, `"sarif"`, `"html"` |

**Response fields:**

```json
{
  "status": "ok",
  "verdict": "BREAKING",
  "exit_code": 4,
  "summary": {
    "breaking": 2,
    "api_breaks": 0,
    "risk_changes": 0,
    "compatible": 1,
    "total_changes": 3
  },
  "changes": [
    {
      "kind": "func_removed",
      "symbol": "_Z6helperv",
      "description": "Public function removed: helper",
      "impact": "breaking",
      "old_value": "helper",
      "new_value": null,
      "source_location": null
    }
  ],
  "suppressed_count": 0,
  "report": "..."
}
```

The `verdict` field is one of: `NO_CHANGE`, `COMPATIBLE`, `COMPATIBLE_WITH_RISK`, `API_BREAK`, `BREAKING`.

The `exit_code` matches CLI semantics: `0` = safe, `2` = API break, `4` = binary ABI break.

---

### `abi_dump` — Extract ABI snapshot

Extracts the public ABI surface from a shared library and its headers into a JSON snapshot.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `library_path` | string | yes | Path to .so/.dll/.dylib file |
| `headers` | string[] | no | Public header file paths (required for ELF) |
| `include_dirs` | string[] | no | Extra include directories |
| `version` | string | no | Version label (default: `"unknown"`) |
| `language` | string | no | `"c++"` (default) or `"c"` |
| `output_path` | string | no | Write snapshot to file; otherwise returned inline |

**Response fields:**

```json
{
  "status": "ok",
  "summary": {
    "library": "libfoo.so.1",
    "version": "1.2.3",
    "platform": "elf",
    "functions": 42,
    "variables": 3,
    "types": 12,
    "enums": 5
  },
  "snapshot": { "..." }
}
```

---

### `abi_list_changes` — List detectable change kinds

Enumerates all 113 `ChangeKind` values with their impact classification.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `impact` | string | no | Filter: `"breaking"`, `"api_break"`, `"risk"`, or `"compatible"` |

**Response:**

```json
{
  "count": 113,
  "change_kinds": [
    {
      "kind": "func_removed",
      "impact": "breaking",
      "default_verdict": "BREAKING",
      "description": "Old binaries call a symbol that no longer exists..."
    }
  ]
}
```

---

### `abi_explain_change` — Explain a specific change kind

Returns a detailed explanation of what a change kind means, why it's dangerous, and how to fix it.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `change_kind` | string | yes | e.g. `"func_removed"`, `"type_size_changed"` |

**Response:**

```json
{
  "kind": "type_size_changed",
  "impact": "breaking",
  "default_verdict": "BREAKING",
  "severity": "error",
  "description": "Old code allocates or copies the type with the old size; heap/stack corruption, out-of-bounds access.",
  "fix_guidance": "This is a binary ABI break. Options: (1) revert the change, (2) bump the SONAME/major version, (3) add the old symbol as a compatibility alias."
}
```

## Agent workflow examples

### Check a PR for ABI compatibility

```text
Agent: "Check if this PR breaks ABI"

1. abi_compare(old_input="baseline.json", new_input="build/libfoo.so",
               new_headers=["include/foo.h"])
   → verdict: BREAKING, changes: [{kind: "func_removed", ...}]

2. abi_explain_change(change_kind="func_removed")
   → "Old binaries call a symbol that no longer exists..."

3. Agent posts PR comment with findings and fix suggestions
```

### Developer asks "Is my struct change safe?"

```text
User: "I added a field to FooConfig — is this ABI safe?"

1. abi_compare(old_input="old.json", new_input="new.json")
   → verdict: BREAKING, changes: [{kind: "type_size_changed", ...}]

2. abi_explain_change(change_kind="type_size_changed")
   → "Old code allocates the type with the old size; heap/stack corruption."

3. Agent suggests using a pointer to an opaque extension struct instead
```

### Explore what abicheck detects

```text
Agent: "What kinds of ABI breaks can you detect?"

1. abi_list_changes(impact="breaking")
   → 50+ change kinds with descriptions

2. Agent summarizes the categories for the user
```

## Transport

The server uses **stdio** transport — the agent spawns `abicheck-mcp` as a local subprocess and communicates over stdin/stdout. No network, no ports, no deployment needed.

## Architecture

```text
┌──────────────────────────────────┐
│   MCP Client (Agent / IDE)       │
│   Claude Code, Cursor, VS Code   │
└──────────┬───────────────────────┘
           │ stdio (JSON-RPC)
           ▼
┌──────────────────────────────────┐
│   abicheck-mcp                   │
│   abicheck/mcp_server.py         │
│                                  │
│   Tools:                         │
│     abi_dump                     │
│     abi_compare                  │
│     abi_list_changes             │
│     abi_explain_change           │
└──────────┬───────────────────────┘
           │ Python imports
           ▼
┌──────────────────────────────────┐
│   abicheck core library          │
│   dumper / checker / reporter    │
└──────────────────────────────────┘
```

## Security

### Path restrictions for `output_path`

When `abi_dump` writes a snapshot to disk via `output_path`, the MCP server
enforces the following policy:

- **Extension**: only `.json` files are allowed
- **System directories**: writes to `/etc`, `/bin`, `/sbin`, `/usr/bin`,
  `/usr/sbin`, `/boot`, `/sys`, `/proc`, `/dev` are blocked on Linux/macOS;
  `C:\Windows\`, `C:\System32\` etc. are blocked on Windows
- **Credential directories**: `~/.ssh`, `~/.aws`, `~/.gnupg` are always blocked
- **Symlink-safe**: resolved paths are used for comparison to prevent traversal
  via `../../etc/` or `//etc/` bypasses

Read paths (`library_path`, `headers`, `include_dirs`) are not restricted —
they follow the same access controls as the user running the MCP server.
