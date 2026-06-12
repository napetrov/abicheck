# Build/Source Redesign — Implementation Plan (internal)

> Internal implementation checklist for evolving the buildsource feature to a
> source-tree-centric model. **Not a published ADR** — the decisions below are
> folded into ADRs 028–033 (with status updates); this file is the working plan.

**Date:** 2026-06-12
**Status:** Proposed
**Decision maker:** Nikolay Petrov

---

## Context

ADR-028..033 introduced optional build/source/graph evidence. After the
evidence→**buildsource** rename (PR #356) the feature collects normalized facts
and embeds them inline in the `.abi.json` (single-artifact UX). Using the
feature in practice exposed three rough edges in the original, *build-tree-centric*
design:

1. **The build directory is the wrong center of gravity.** The realistic
   baseline-prep case is a **prebuilt package** (e.g. a conda-forge `.so`) plus
   the **source checkout at the git tag it was built from**. There is no
   `build/` to point at, yet that is exactly when source evidence (L4/L5) is
   most valuable.
2. **`--source-abi` / `--source-graph` are redundant knobs.** Passing a source
   tree *is* the instruction to do source analysis; the graph is cheap and
   derived. Users should not have to ask for them separately.
3. **Build/source facts are hard to prepare in parallel.** Build-side and
   source-side data may be produced on different machines, at different times,
   from different locations. There was no way to produce them independently and
   combine them into one baseline.

A fourth need surfaced for real projects: a source checkout often *contains* the
build-system setup, and abicheck could use it to recover exact ABI-affecting
flags and generated headers — but only with project-specific configuration
(oneDAL, for example, supports **both** Make and Bazel; abicheck cannot guess
which produced the artifact, nor how to invoke it).

This ADR records the resulting model. It **extends** ADR-028 (D6 CLI),
ADR-029 (D3/D10 inputs), ADR-030 (D7 scopes), and ADR-033 (D2 modes); it does
not change the authority rule (ADR-028 D3) or the action/security ceiling
(ADR-032 D5).

---

## Decision

### D1. Three independent inputs, from anywhere

A scan consumes up to three inputs, each resolvable from a different location:

| Input | What | Supplies |
|---|---|---|
| **binary / package** | the shipped `.so`/`.dll`/`.dylib` (e.g. from conda-forge) | L0/L1 |
| **public headers** | `-H include/` | L2 |
| **source tree** | a checkout at the build tag (`--sources <dir>`) | L4 + L5 |
| **build metadata** *(optional)* | a compile DB / build-system query output (`--build-info <path>`) | L3 |

None of these is required to live next to the others. The build-tree-centric
framing of ADR-029 ("collect from `build/`") becomes one *special case* of
"point `--build-info` at wherever the flags are".

### D2. `--sources <tree>` is the source input; L4 + L5 are automatic

Passing `--sources <source-tree>` to `dump` runs source ABI replay (L4) and
builds the source graph summary (L5) **internally** and embeds both. The former
`--source-abi` and `--source-graph` *user-facing* flags are removed; the graph
is always built when a source surface exists (it is compact by design,
ADR-031 D7). Replay still requires a C++ front-end (clang, or castxml for the
declaration subset); if absent, L4/L5 degrade to partial coverage and the
artifact tiers stay authoritative (ADR-030, ADR-028 D7) — the scan never aborts.

### D3. Build metadata is optional and decoupled

`--build-info <path>` (a compile DB, a build directory, or a pre-captured
build-evidence pack) is optional and independent of `--sources`. When omitted,
abicheck auto-discovers a `compile_commands.json` inside the source tree if one
is present, else skips L3 silently and reports it as `not_collected`. The
conda-forge-binary + source-from-tag case therefore works with **no build tree
at all** — L3 flag-drift is best-effort when build metadata happens to exist.

### D4. Build-tool query configuration (read by default, query opt-in, never a full build)

When a source tree carries a build system, abicheck can use it to recover exact
flags and generated headers — gated by a per-project config and the ADR-032 D5
action ceiling:

```yaml
# .abicheck.yml at the source-tree root (or --build-config <path>)
build:
  system: bazel            # bazel | cmake | make | meson | auto (default: auto-detect)
  # Command that EMITS flags/exports without performing a full project build —
  # e.g. a configured-graph/action query, not `cmake --build` / `make all`.
  query: "bazel cquery 'deps(//cpp/oneapi/dal:core)' --output=jsonproto"
  compile_db: bazel-out/.../compile_commands.json   # where flags land, if any
sources:
  public_headers: ["cpp/oneapi/dal/**/*.hpp"]
  exclude: ["**/test/**", "**/backend/**"]
```

The action policy is exactly ADR-032 D5:

- **`inspect` (default, always on):** read existing build outputs / compile DBs
  the checkout already has. No config needed.
- **`query_build_system` (opt-in, `--allow-build-query`):** run the configured
  *query/extraction* command (Bazel `cquery`/`aquery`, Ninja `-t`, `make -n`,
  CMake File API regeneration) to emit flags/exports. This is the "run build
  commands to get exports, but not an actual build" tier.
- **`run_build` / `wrap_build` (denied):** abicheck never performs a full
  project build or compiler-wrapper interception. Those remain out of scope for
  the default tooling.

For multi-build-system projects (oneDAL's Make *and* Bazel), `build.system` +
`build.query` disambiguate which toolchain produced the artifact and how to
interrogate it.

### D5. `merge` — combine independently-produced dumps into one baseline

```bash
# Produce each side wherever/whenever is convenient:
abicheck dump --sources ./libfoo-src/        -o libfoo.src.json   # source facts only (no binary)
abicheck dump libfoo.so -H include/          -o libfoo.bin.json   # artifact facts
# Combine into one self-contained baseline:
abicheck merge libfoo.bin.json libfoo.src.json -o libfoo.baseline.json
```

`merge` folds the embedded `build_source` payloads (and the snapshot surfaces)
from both inputs, reusing the `_combine_packs` per-layer merge already used by
`dump`/`compare` (each layer's facts come from the side that supplies them; the
coverage manifest is rebuilt per layer, never over-claiming). This makes
baseline preparation parallelizable and is the primary motivation for the
single-artifact embedding.

### D6. `collect` demotes to an advanced command

With `dump --sources`/`--build-info` doing inline collection + embedding,
`collect` is no longer on the common path. It remains for advanced use: raw
provenance retention, external CLI extractors (ADR-032 D3), per-TU caching, and
audit mode. The common workflow never needs it.

### D7. Single-artifact storage is the default

The normalized facts ride inline in the `.abi.json` (ADR-028 D8, implemented in
PR #356), so `compare old.json new.json` carries L3/L4/L5 with no out-of-band
directories. The on-disk pack directory remains an optional override
(`--old/--new-build-info`, `--old/--new-sources`) and the raw-provenance home.

---

## Consequences

### Positive

- Matches the real baseline-prep workflow (prebuilt package + source tag).
- Removes redundant flags; the graph "just happens".
- Parallel, combinable baseline preparation via `merge`.
- Reuses real build flags/generated headers for accurate L4, with an explicit,
  auditable, build-but-don't-build security posture.

### Negative / risks

- Inline source replay in `dump` is heavier than attaching a prebuilt pack;
  scoping (ADR-030 D7) and caching (D8) matter more.
- Build-tool config is one more project file to learn; auto-detection mitigates.
- `query_build_system` commands vary in portability across projects.

---

## Implementation plan

| Phase | Scope | Status |
|---|---|---|
| 1 | `dump --sources <tree>` runs inline L4 replay + L5 graph (reuse `run_source_replay`/`build_source_graph`), embeds them; the common path needs no `--source-abi`/`--source-graph` toggles (`--sources` implies both) | ✅ Done — `buildsource/inline.py`, `embed_build_source` |
| 2 | `--build-info <path>` accepts a build dir / compile DB / pack; auto-discover compile DB in the source tree | ✅ Done — `inline._resolve_compile_db` / `_autodiscover_compile_db` |
| 3 | `abicheck merge a.json b.json -o out.json` over embedded `build_source` (+ surfaces) | ✅ Done — `cli_buildsource.merge_cmd` |
| 4 | `.abicheck.yml` `build:` config + `--build-config`/`--allow-build-query`; wire to the ADR-032 action ceiling | ✅ Done — `inline.BuildConfig` / `_run_build_query`, `--build-config`/`--allow-build-query` on `dump` |
| 5 | Demote `collect` to advanced; update docs/getting-started to the source-tree flow | ✅ Done — `docs/concepts/build-source-data.md` Workflow rewrite |
| 6 | Reword ADR-028 D6 / ADR-029 D3,D10 / ADR-030 D7 / ADR-033 D2 to reference this model | ✅ Done — ADR amendment sections (2026-06-12) |

**Back-compat note:** the `collect` command keeps its `--source-abi`/`--source-graph`
flags (it is the advanced pack producer); a pack directory it writes is
auto-detected by `manifest.json` and embedded as before. Only the *common
`dump` path* changed — `--sources` now takes a source tree and implies L4+L5.

---

## Relationship to other ADRs

- **ADR-028** — extends D6 (CLI) and D8 (embedded storage); authority rule (D3) unchanged.
- **ADR-029** — generalizes D3/D10 (build inputs) beyond the build tree.
- **ADR-030** — `--sources` selects replay scope automatically (D7 mapping).
- **ADR-032** — D4 is a direct application of the D5 action ceiling; no new capability.
- **ADR-033** — the CI evidence modes (D2) select these inputs/scopes internally.
