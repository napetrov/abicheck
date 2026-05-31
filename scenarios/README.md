# User-Scenario / Flow Catalog

This directory defines **how real people use libraries, binaries, and
abicheck** — the user flows and use cases for the tool itself — and drives
**end-to-end validation** that abicheck works as a usable **scanner tool**, not
only as an ABI/API-change detector.

It is a **first-class, separate entity**. Don't confuse it with:

| Entity | What it is | Lives in |
|---|---|---|
| **Scenarios** (here) | A *user flow*: a persona, a real situation, the abicheck commands they run, and the outcome they expect. Drives end-to-end tool validation. | `scenarios/` |
| **Examples** | Compilable C/C++ code demonstrating one specific ABI/API *change* (change-type fixtures). Validation + documentation of *detection*. | `examples/` |
| **Plans** | The backlog of *capability gaps* to close. | `docs/development/plans/` |

## Why this exists

abicheck must do two things: (1) correctly classify an ABI/API change, and
(2) be usable as a scanner in a real workflow — CI gate, compliance scan,
SARIF for code scanning, offline snapshots, public-surface scoping, accepting
known breaks. The example catalog covers (1) exhaustively but every case runs
through a single `compare`. This catalog covers (2): the *flows*.

It also captures **missed usage scenarios**. [Issue #235](https://github.com/napetrov/abicheck/issues/235)
was filed because abicheck reported *private* ABI breaks even when public
headers were supplied — a compliance-scanner flow we hadn't pinned down. That
flow is now `SC-PUBLIC-SURFACE-SCOPE`, validated end-to-end so it can't regress.

## The catalog

Authoritative, machine-readable: [`scenarios.yaml`](scenarios.yaml). Each entry
has a `persona`, `narrative`, `flow` (the commands), `expected` outcome, and a
`validates` link to a use case in
[`docs/development/usecase-registry.yaml`](../docs/development/usecase-registry.yaml).

| Scenario | Persona | Validates | Automated |
|---|---|---|---|
| `SC-CI-GATE-BREAKING` | CI engineer | compare gate | ✅ |
| `SC-CI-GATE-ADDITIVE` | CI engineer | compare gate | ✅ |
| `SC-EXIT-CONTRACT` | CI engineer | exit codes 0/2/4 | ✅ |
| `SC-PUBLIC-SURFACE-SCOPE` (issue #235) | Library maintainer | public-surface scoping | ✅ |
| `SC-SCAN-SARIF` | AppSec engineer | SARIF for code scanning | ✅ |
| `SC-RELEASE-RECOMMENDATION` | Library maintainer | semver/SONAME recommendation | ✅ |
| `SC-ACCEPT-KNOWN-BREAK` | Library maintainer | suppression flow | ✅ |
| `SC-OFFLINE-SNAPSHOT` | Release engineer | snapshot interchange | ✅ |
| `SC-PACKAGE-RELEASE-SCAN` | Distro packager | release/bundle scan | planned |
| `SC-APP-IMPACT` | Application developer | appcompat | planned |
| `SC-SYSROOT-MIGRATION` | Platform engineer | stack-check | planned |
| `SC-AGENT-MCP` | AI agent | MCP server | planned |

## How it is validated

`tests/test_scenarios.py` is the driver:

- structural validity, and every `validates` points at a real registry use case;
- every `automated: true` scenario has a `test` that **invokes the abicheck CLI
  end-to-end** (via `CliRunner` on JSON snapshots — no castxml/gcc needed) and
  asserts the documented `expected` outcome (exit code, verdict, SARIF, …);
- every non-automated scenario is `status: planned` with a plan or note.

## Adding a scenario

1. Add an entry to `scenarios.yaml` (`persona`, `narrative`, `flow`,
   `expected`, `validates`).
2. If automatable now, add a `test: test_sc_<name>` and implement it in
   `tests/test_scenarios.py` driving the real CLI. Otherwise set
   `automated: false`, `status: planned`, and link a `plan:` or add a `note:`.
3. Run `pytest tests/test_scenarios.py`.

**Found a missed usage scenario (like #235)? Add it here immediately** — that is
how it becomes a permanent end-to-end regression guard.
