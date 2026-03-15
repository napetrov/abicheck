# MCP Support Plan for abicheck

## Motivation

Agents (Claude Code, OpenAI Agents, Cursor, etc.) currently interact with abicheck
only through the CLI, which requires:

1. Knowing the exact CLI flags and argument order
2. Parsing human-readable markdown/text output back into structured data
3. Managing file paths and intermediate JSON snapshots manually
4. No discoverability — the agent must be pre-taught about abicheck

**MCP (Model Context Protocol)** solves all of these by exposing abicheck as a
set of typed, self-describing tools that any MCP-compatible agent can discover,
call with structured parameters, and receive structured JSON responses from.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│           MCP Client (Agent / IDE)              │
│  Claude Code, Cursor, VS Code, OpenAI Agents    │
└──────────────────┬──────────────────────────────┘
                   │  stdio or Streamable HTTP
                   ▼
┌─────────────────────────────────────────────────┐
│          abicheck MCP Server                    │
│          abicheck/mcp_server.py                 │
│                                                 │
│  Tools:                                         │
│    • abi_dump        — dump ABI snapshot         │
│    • abi_compare     — compare two ABI surfaces  │
│    • abi_list_changes — list change kinds        │
│    • abi_explain_change — explain a change kind  │
│                                                 │
│  Resources:                                     │
│    • snapshot://{path} — read a saved snapshot   │
│    • policy://builtin/{name} — built-in policy  │
│                                                 │
│  Prompts:                                       │
│    • check-abi-compatibility                    │
│    • review-abi-changes                         │
│                                                 │
└──────────────────┬──────────────────────────────┘
                   │  Python imports
                   ▼
┌─────────────────────────────────────────────────┐
│        abicheck core library                    │
│  dumper.dump() / checker.compare() / reporter   │
└─────────────────────────────────────────────────┘
```

---

## Proposed MCP Tools

### 1. `abi_dump` — Dump ABI Snapshot

**Purpose:** Extract the ABI surface of a shared library + headers into a
structured JSON snapshot.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `library_path` | `string` | yes | Path to .so / .dll / .dylib file |
| `headers` | `string[]` | yes (ELF) | Public header file path(s) |
| `include_dirs` | `string[]` | no | Extra include directories for castxml |
| `version` | `string` | no | Version label (default: "unknown") |
| `language` | `"c++"  \| "c"` | no | Language mode (default: "c++") |
| `output_path` | `string` | no | Save snapshot to file (if omitted, returned inline) |

**Returns:** JSON object with:
- `snapshot`: The full ABI snapshot (when `output_path` is omitted) or path to the written file
- `summary`: `{ functions: int, variables: int, types: int, enums: int }`
- `library`: Library name detected
- `platform`: `"elf"` / `"pe"` / `"macho"`

**Why agents need this:** Agents can dump a snapshot, inspect it, and decide
whether to proceed with a comparison — all without shelling out to CLI.

---

### 2. `abi_compare` — Compare Two ABI Surfaces

**Purpose:** The core operation — diff two library versions and report breaking changes.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `old_input` | `string` | yes | Path to old .so, .dll, .dylib, or JSON snapshot |
| `new_input` | `string` | yes | Path to new .so, .dll, .dylib, or JSON snapshot |
| `old_headers` | `string[]` | no | Headers for old side (required if old is ELF binary) |
| `new_headers` | `string[]` | no | Headers for new side (required if new is ELF binary) |
| `headers` | `string[]` | no | Headers for both sides (shorthand) |
| `include_dirs` | `string[]` | no | Include directories for both sides |
| `language` | `"c++" \| "c"` | no | Language mode (default: "c++") |
| `policy` | `"strict_abi" \| "sdk_vendor" \| "plugin_abi"` | no | Built-in policy (default: "strict_abi") |
| `policy_file` | `string` | no | Path to custom YAML policy file |
| `suppression_file` | `string` | no | Path to YAML suppression file |
| `format` | `"json" \| "markdown" \| "sarif" \| "html"` | no | Output format (default: "json") |

**Returns:** JSON object with:
- `verdict`: One of `NO_CHANGE`, `COMPATIBLE`, `COMPATIBLE_WITH_RISK`, `API_BREAK`, `BREAKING`
- `exit_code`: `0`, `2`, or `4` (matches CLI semantics)
- `summary`: `{ breaking: int, api_breaks: int, risk_changes: int, compatible: int }`
- `changes`: Array of change objects `{ kind, symbol, description, impact }`
- `suppressed_count`: Number of suppressed changes
- `report`: Full rendered report in requested format (markdown/sarif/html)

**Why agents need this:** This is the primary tool. An agent can call it, read
the structured verdict and changes array, and reason about ABI compatibility
without parsing markdown tables.

---

### 3. `abi_list_changes` — List All Change Kinds

**Purpose:** Enumerate all 85+ `ChangeKind` values with their impact classification
and description.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `impact` | `"breaking" \| "api_break" \| "risk" \| "compatible"` | no | Filter by impact level |

**Returns:** Array of `{ kind: string, impact: string, description: string }`

**Why agents need this:** Gives agents a reference catalog they can use to
understand what each change kind means, filter changes by severity, or explain
findings to users.

---

### 4. `abi_explain_change` — Explain a Specific Change Kind

**Purpose:** Get a detailed explanation of what a specific ABI change kind means,
why it's dangerous, and how to fix it.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `change_kind` | `string` | yes | The ChangeKind to explain (e.g. `func_removed`) |

**Returns:** JSON object with:
- `kind`: The change kind
- `impact`: Impact classification
- `description`: Human-readable explanation
- `risk`: Why this change is dangerous
- `fix_guidance`: How to resolve the issue
- `example_case`: Link to relevant example case (if available)

**Why agents need this:** When an agent sees a `type_vtable_changed` in results,
it can call this tool to understand what happened and suggest a fix to the user.

---

## Proposed MCP Resources

### 1. `snapshot://{path}` — Read ABI Snapshot

Expose saved JSON snapshots as MCP resources so agents can browse/read them
without explicit file I/O.

### 2. `policy://builtin/{name}` — Built-in Policy Details

Expose the three built-in policies (`strict_abi`, `sdk_vendor`, `plugin_abi`)
as readable resources showing which change kinds map to which verdicts.

---

## Proposed MCP Prompts

### 1. `check-abi-compatibility`

Pre-built prompt template that guides the agent through a full ABI check workflow:

```
Given a library at {library_path} with headers at {header_paths},
compare the old version at {old_path} with the new version at {new_path}.
Report any ABI breaks and suggest fixes.
```

### 2. `review-abi-changes`

Pre-built prompt for reviewing a comparison result and producing a
human-readable summary with fix suggestions:

```
Review the following ABI comparison result and explain each breaking
change. Suggest concrete fixes for each issue.
```

---

## Implementation Plan

### Phase 1: Core MCP Server (MVP)

**Files to create/modify:**

1. **`abicheck/mcp_server.py`** (new) — FastMCP server with 4 tools
   - Uses `from mcp.server.fastmcp import FastMCP`
   - Wraps existing `dumper.dump()` and `checker.compare()` functions
   - Returns structured JSON (reuses `reporter.to_json()` internally)
   - Handles errors gracefully, returning error messages instead of exceptions

2. **`pyproject.toml`** — Add MCP dependencies and entry point
   ```toml
   [project.optional-dependencies]
   mcp = ["mcp[cli]>=1.2.0"]

   [project.scripts]
   abicheck = "abicheck.cli:main"
   abicheck-mcp = "abicheck.mcp_server:main"
   ```

3. **`tests/test_mcp_server.py`** (new) — Unit tests for MCP tools
   - Test each tool with mock inputs
   - Test error handling (missing files, bad parameters)
   - Test that JSON responses are well-formed

### Phase 2: Resources & Prompts

4. **Add MCP resources** to `mcp_server.py`
   - `snapshot://` resource for reading saved snapshots
   - `policy://` resource for inspecting built-in policies

5. **Add MCP prompts** to `mcp_server.py`
   - `check-abi-compatibility` prompt template
   - `review-abi-changes` prompt template

### Phase 3: Integration & Documentation

6. **`docs/mcp.md`** (new) — MCP integration guide
   - How to configure in Claude Desktop, Cursor, VS Code
   - Example `claude_desktop_config.json` / `.mcp.json` configuration
   - Example agent workflows

7. **Example configurations:**
   ```json
   {
     "mcpServers": {
       "abicheck": {
         "command": "abicheck-mcp",
         "args": []
       }
     }
   }
   ```

---

## Design Decisions

### Why `mcp[cli]` as optional dependency?

Not all users need MCP support. Making it optional (`pip install abicheck[mcp]`)
keeps the base install lightweight while allowing MCP users to opt in.

### Why separate entry point (`abicheck-mcp`)?

The MCP server runs as a long-lived process (stdio or HTTP), which is
fundamentally different from the one-shot CLI. A separate entry point keeps
concerns clean and allows `abicheck` CLI to remain unchanged.

### Why return JSON by default in MCP tools?

Agents consume structured data. While the CLI defaults to markdown (for humans),
MCP tools should default to JSON so agents can parse and reason about results
programmatically. The `format` parameter still allows requesting markdown/HTML
for display to users.

### Why include `abi_list_changes` and `abi_explain_change`?

These "reference" tools are what make the MCP server truly agent-friendly.
Without them, an agent sees `type_vtable_changed` in results but has no way to
understand what it means. With them, the agent can self-serve explanations and
provide rich, contextual guidance to users.

### Stdio vs Streamable HTTP transport?

Phase 1 uses **stdio** (simplest, works with all MCP clients). Streamable HTTP
can be added later for remote/shared deployments but is not needed for the
primary use case of local agent integration.

---

## Configuration Examples

### Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "abicheck": {
      "command": "abicheck-mcp",
      "args": []
    }
  }
}
```

### With uv (no install required)

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

### Cursor / VS Code

Same format in `.cursor/mcp.json` or VS Code MCP settings.

---

## Agent Workflow Examples

### Example 1: CI Agent Checking a PR

```
Agent receives: "Check if this PR breaks ABI compatibility"

1. Agent calls abi_dump with old library + headers → gets baseline snapshot
2. Agent calls abi_dump with new library + headers → gets new snapshot
3. Agent calls abi_compare with both snapshots → gets verdict + changes
4. If BREAKING:
   - Agent calls abi_explain_change for each breaking change
   - Agent posts PR comment with findings and fix suggestions
5. If COMPATIBLE: Agent approves the PR
```

### Example 2: Developer Asks "Is my change safe?"

```
User: "I changed struct FooConfig — is this ABI safe?"

1. Agent calls abi_compare on old vs new .so with headers
2. Gets back: type_size_changed on FooConfig (BREAKING)
3. Agent calls abi_explain_change("type_size_changed")
4. Agent explains: "Adding a field changed the struct size from 24 to 32 bytes.
   Any code compiled against the old header will allocate the wrong amount of
   memory. Consider adding the field to a reserved area or using a pointer to
   an opaque extension struct."
```

### Example 3: Agent Explores Available Checks

```
Agent: "What kinds of ABI breaks can abicheck detect?"

1. Agent calls abi_list_changes(impact="breaking")
2. Gets back 50+ change kinds with descriptions
3. Agent summarizes the categories for the user
```

---

## Success Criteria

- [ ] `abicheck-mcp` starts and responds to MCP tool discovery
- [ ] All 4 tools work end-to-end with real .so files and JSON snapshots
- [ ] Claude Code can discover and use abicheck tools via MCP config
- [ ] Structured JSON responses are parseable without post-processing
- [ ] Error cases return helpful messages (not stack traces)
- [ ] Existing CLI remains unchanged (no regressions)
- [ ] MCP dependency is optional (`pip install abicheck[mcp]`)
