# Multi-binary (bundle) ABI analysis

Most ABI tools answer one question: *"did this `.so` file's ABI change?"*
Real-world releases — oneDAL, libtorch, Intel MKL, the bundled CUDA
runtime — ship **several `.so` files that depend on each other**.
Per-library compare misses entire classes of breakage that live in the
relationships between siblings. The **bundle layer** (ADR-023) fixes
that.

This page covers:

- What "bundle analysis" actually checks
- The new `compare-release` flags and what they do
- The manifest file format
- How to read the JSON / markdown output
- When you'd want to turn it off

## What the bundle layer catches

| Scenario | Per-library compare says | Bundle layer says |
|---|---|---|
| `libcore.so` removes `core_mul`; `libalgo.so` still imports it | libcore: BREAKING; libalgo: NO_CHANGE | + `bundle_intra_dep_removed` on libalgo |
| `libcore.so` changes `core_add(int,int)` → `core_add(long,long)` (extern C, same mangled name); libalgo is byte-identical | libcore: BREAKING; libalgo: NO_CHANGE | + `bundle_intra_dep_signature_changed` on libalgo |
| Type `detail::Context` defined in libcore changes layout; libalgo's exported symbols embed it as a template parameter | libcore: BREAKING; libalgo: NO_CHANGE | + `bundle_intra_type_changed` on libalgo |
| `shared_util` moves from libcore to libutil; bundle still exports it once | libcore: BREAKING (`func_removed`); libutil: COMPATIBLE (`func_added`) | + `bundle_provider_changed` (COMPATIBLE_WITH_RISK) |
| Removed library was depended on by a surviving sibling | libcore removed (worst-of) | + `bundle_library_removed` with consumer attribution |
| Symbol's `gnu.version_d` tag drifts (`GLIBCXX_3.4.20` → `GLIBCXX_3.4.30`) | unchanged | + `bundle_intra_dep_resolved_to_different_version` |
| Manifest promises `train_double_sparse`; new bundle doesn't export it | per-library `func_removed` (can't tell promised from incidental) | + `bundle_manifest_instantiation_removed` |

Per-library findings are unchanged — the bundle layer only **adds**
cross-library findings; it never hides them. The aggregate `verdict`
becomes the worst of `bundle_verdict` and the per-library worst.

## Running it

The bundle layer is **enabled by default**:

```bash
abicheck compare-release release-1.0/ release-2.0/ -H include/
```

If the bundle is broken, you'll see a new section in the markdown
summary and new top-level keys in the JSON output:

```text
| **Verdict** | ❌ `BREAKING` |
| **Bundle**  | ❌ `BREAKING` (2 cross-library findings) |

## 🔗 Bundle (Cross-Library) Findings

- **bundle_intra_dep_removed** — `core_mul` (consumer: `libalgo.so`)
  - libalgo.so imports core_mul, but no library in the new bundle exports it.
    Runtime load of libalgo.so will fail with undefined symbol.
- **bundle_intra_dep_signature_changed** — `core_add` (consumer: `libalgo.so`) (provider: `libcore.so`)
  - libalgo.so calls core_add (mangled name unchanged) but libcore.so
    altered its DWARF signature. Calling convention is now mismatched.
```

## The three new flags

### `--manifest PATH`

A **manifest** is a YAML or JSON file that lists the symbols your
release publicly promises to ship. With `--manifest`, the bundle layer
enforces the contract: every promised symbol must be exported by some
library in the new bundle.

Without a manifest, per-library `func_removed` already flags the symbol
disappearing — but the tool can't tell whether that symbol was a
*promised* part of the public ABI or an internal helper that happened
to be visible. The manifest externalises the contract.

**Format:**

```yaml
# release-2.0/manifest.yaml
version: 1
provides:
  - symbol: _ZN6oneapi3dal9train_opsIfNS0_6methodE7defaultENS0_4taskE5trainEEvv
    library: libonedal_core.so.1
    optional_provider: false
  - symbol: oneapi_dal_version
    library: libonedal_core.so.1
    optional_provider: false
  - symbol: any_train_op_helper
    optional_provider: true   # any sibling may provide it
```

Each entry has:

- `symbol` *(required)* — the exported symbol name (mangled for C++,
  plain for `extern "C"`).
- `library` *(optional)* — required when `optional_provider: false`.
  Names a specific library (filename like `libcore.so` or SONAME like
  `libcore.so.1` both work).
- `optional_provider` *(default `true`)* — when `true`, any sibling in
  the bundle can satisfy the promise; when `false`, the symbol must be
  provided by the named `library`. Must be a real boolean (`true` /
  `false`); the manifest loader rejects string `"false"` or integer
  `1` to prevent silent contract weakening.

**Verdicts:**

| Manifest entry status in new bundle | ChangeKind | Default verdict |
|---|---|---|
| Promised symbol missing | `bundle_manifest_instantiation_removed` | BREAKING |
| Promised at wrong provider (when `optional_provider: false`) | `bundle_manifest_instantiation_removed` | BREAKING |
| Manifest lists a symbol that the old bundle didn't export | `bundle_manifest_instantiation_added` | COMPATIBLE (addition) |

A malformed manifest aborts the run with a `ClickException`. A failing
`--manifest` is treated as a user error, not an environmental quirk —
unlike the bundle-engine-internal failures, which degrade to per-library
results with a warning.

### `--bundle-system-providers libfoo,libbar`

The bundle layer needs to distinguish *intra-bundle imports* (a sibling
should be providing this symbol) from *external imports* (the symbol
comes from the system loader: libc, libstdc++, libgcc_s, libpthread,
libtbb, libsycl, OpenCL, ...). The built-in allow-list handles the
canonical set; this flag extends it.

When to use it:

- Your bundle uses an external SDK shipped outside the release tarball
  (e.g. a vendor library like `libvpl.so.2` that consumers install
  separately).
- A `--manifest`-free workflow keeps emitting `bundle_intra_dep_removed`
  findings against symbols you know are external.

Example:

```bash
abicheck compare-release old/ new/ \
    --bundle-system-providers libvpl.so.2,libcuda.so.1
```

These sonames are appended to the built-in allow-list for this run only.

### `--no-bundle-analysis`

Skip bundle analysis entirely. Use this when:

- You're debugging a per-library issue and want to suppress the noise.
- You want **parity output** with the pre-ADR-023 behaviour of
  `compare-release` (for instance, comparing a CI run from before the
  bundle layer landed).
- The bundle layer raised a warning ("bundle analysis skipped: ..."),
  you want a clean run, and you've already filed a bug.

This flag is the explicit opt-out. There is no environment variable
equivalent; the flag must appear in the command line.

## JSON output schema additions

`compare-release --format json` adds two top-level keys when bundle
analysis ran:

```json
{
  "verdict": "BREAKING",                  // existing: worst of per-lib × bundle
  "libraries": [...],                     // existing
  "unmatched_old": [],                    // existing
  "unmatched_new": [],                    // existing
  "warnings": [],                         // existing
  "bundle_verdict": "BREAKING",           // new (ADR-023)
  "bundle_findings": [                    // new (ADR-023)
    {
      "kind": "bundle_intra_dep_removed",
      "symbol": "core_mul",
      "consumer_library": "libalgo.so",
      "provider_library": null,
      "description": "libalgo.so imports core_mul, but no library in the new bundle exports it. Runtime load of libalgo.so will fail with undefined symbol.",
      "old_value": null,
      "new_value": null,
      "affected_libraries": ["libalgo.so"]
    }
  ]
}
```

`bundle_findings` is `[]` (empty list) when bundle analysis ran and
found nothing. The keys are **omitted entirely** when
`--no-bundle-analysis` is passed — downstream consumers that need to
distinguish "no findings" from "didn't run" should check for key
presence.

Each finding has:

- `kind` — one of the nine `bundle_*` ChangeKind values
  (see [Change Kinds reference](../reference/change-kinds.md)).
- `symbol` — mangled symbol name (or library name for
  `bundle_library_*` findings).
- `consumer_library` — the sibling whose ABI is affected (nullable).
- `provider_library` — the sibling that caused the change (nullable).
- `old_value` / `new_value` — provider/version migration details when
  applicable.
- `affected_libraries` — list of every library affected by this finding;
  enables fan-out filtering downstream.

## Exit codes

Same as before, but a bundle finding can promote the verdict:

| Exit | Meaning |
|---|---|
| 0 | All clear — no per-library or bundle findings above COMPATIBLE_WITH_RISK |
| 2 | At least one library or bundle finding is API_BREAK |
| 4 | At least one library or bundle finding is BREAKING |
| 8 | Library removed from the bundle (only with `--fail-on-removed-library`) |

If you previously had a green CI on a release and bundle analysis now
flips it red, the finding section in the markdown / JSON tells you what
changed and which consumer is affected. The most common bisect path
is: silence the offending finding with a [suppression](suppressions.md)
or fix the intra-bundle contract.

## Platform support

Bundle analysis is **ELF/Linux-only** (ADR-018, ADR-023). Mach-O and
PE/COFF bundles are out of scope for this iteration — the resolution
graph relies on DT_NEEDED edges and `.gnu.version_r` / `.gnu.version_d`
sections that PE and Mach-O don't have direct equivalents for. On
non-Linux runs, `compare-release` skips bundle analysis silently and
emits per-library results only.

## Programmatic API

The bundle layer is also exposed as a Python module for downstream
tooling:

```python
from abicheck.bundle import (
    build_bundle_snapshot, compare_bundle, load_manifest,
)
from pathlib import Path

old = build_bundle_snapshot({p.name: p for p in Path("old/").glob("*.so")})
new = build_bundle_snapshot({p.name: p for p in Path("new/").glob("*.so")})
manifest = load_manifest(Path("manifest.yaml"))   # optional

# per_library_results is the list of DiffResult returned by
# abicheck.checker.compare() for each library pair.
result = compare_bundle(old, new, per_library_results, manifest=manifest)
print(result.bundle_verdict)        # Verdict.BREAKING / COMPATIBLE / ...
for f in result.bundle_findings:
    print(f.kind, f.symbol, f.consumer_library)
```

## References

- [ADR-023](../development/adr/023-bundle-aware-multi-binary-analysis.md) — design rationale
- [ADR-008](../development/adr/008-full-stack-dependency-validation.md) — the resolver/binder engine the bundle layer reuses
- Example cases:
  [case90 — intra-bundle removed symbol](https://github.com/napetrov/abicheck/tree/main/examples/case90_bundle_intra_dep_removed),
  [case91 — extern-C signature drift](https://github.com/napetrov/abicheck/tree/main/examples/case91_bundle_intra_signature_drift),
  [case92 — provider migration](https://github.com/napetrov/abicheck/tree/main/examples/case92_bundle_provider_changed),
  [case93 — manifest drift](https://github.com/napetrov/abicheck/tree/main/examples/case93_bundle_manifest_drift)
