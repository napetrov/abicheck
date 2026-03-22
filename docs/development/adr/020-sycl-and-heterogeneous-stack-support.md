# ADR-020: SYCL and Heterogeneous Computing Stack Support

**Date:** 2026-03-22
**Status:** Proposed
**Decision maker:** Nikolay Petrov

---

## Context

abicheck currently excels at host-side C/C++ ABI scanning across ELF, PE, and
Mach-O. However, modern SDKs increasingly ship heterogeneous computing stacks
(SYCL, CUDA, HIP) where ABI compatibility spans multiple layers beyond the
host binary.

A feasibility analysis identified SYCL and CUDA as the two major gaps. This
ADR addresses SYCL support and establishes extensibility patterns that CUDA
(and future heterogeneous runtimes) can reuse.

### SYCL-specific ABI layers

SYCL compatibility spans three distinct layers, each with different detection
strategies:

1. **SYCL runtime library ABI** (`libsycl.so` / `libsycl.dll`) — this is a
   standard shared library with exported C++ symbols. Existing ELF/PE/Mach-O
   diff engines already handle this. No new machinery needed.

2. **Plugin Interface (PI)** — DPC++ (and compatible implementations) use a
   backend plugin mechanism where `libsycl.so` dynamically loads backend
   plugins (e.g., `libpi_level_zero.so`, `libpi_opencl.so`, `libpi_cuda.so`).
   Each plugin exports a dispatch table via `piPluginInit()`. PI has a version
   number, and missing/changed entry points break the runtime ↔ plugin
   contract.

3. **Backend driver compatibility** — plugins depend on backend drivers
   (Level Zero, OpenCL ICD, CUDA driver). Version requirements flow through
   the plugin layer. This is analogous to CUDA's toolkit↔driver compatibility
   and is best treated as an environment-matrix constraint.

### What "SYCL ABI break" means in practice

| Scenario | Impact | Detection strategy |
|----------|--------|--------------------|
| Exported symbol removed from `libsycl.so` | Applications crash at load time | Existing ELF diff (already works) |
| Type layout changed in `libsycl.so` exports | Silent data corruption | Existing DWARF diff (already works) |
| PI version bumped | Old plugins rejected at runtime | New: PI metadata extraction + version diff |
| PI entry point removed from dispatch table | Plugin segfaults or returns errors | New: PI entry point set comparison |
| PI plugin `.so` removed from distribution | Backend unavailable | New: Plugin inventory comparison |
| PI plugin discovery path changed | Plugins not found at runtime | New: Plugin search-path diff |
| Backend driver version requirement raised | Runtime fails on older systems | New: Environment matrix constraint |

### Design principles

- **Leverage existing engines**: `libsycl.so` is already fully covered by ELF
  diff. Don't duplicate.
- **Follow established patterns**: New metadata → `SyclMetadata` dataclass
  (like `ElfMetadata`, `PeMetadata`). New detector → `@registry.detector`.
  New change kinds → entries in `change_registry.py`.
- **Heterogeneous-stack extensibility**: The PI plugin pattern generalizes to
  any "host runtime loads backend plugins" architecture. The `SyclMetadata`
  model should be specific to SYCL/PI, but the environment-matrix input
  mechanism should be generic (reusable by CUDA).
- **Implementation-aware**: Target DPC++ (Intel's SYCL) as the primary
  implementation. Other SYCL implementations (hipSYCL/AdaptiveCpp,
  ComputeCpp) can be added later.

---

## Decision

### 1. New metadata model: `SyclMetadata`

```python
@dataclass
class SyclPluginInfo:
    """Metadata for a single PI backend plugin."""
    name: str                          # e.g. "level_zero", "opencl", "cuda"
    library: str                       # e.g. "libpi_level_zero.so"
    pi_version: str                    # PI interface version (from piPluginInit)
    entry_points: list[str]            # exported PI function names
    backend_type: str                  # "level_zero" | "opencl" | "cuda" | "hip"
    min_driver_version: str | None     # minimum backend driver version if known

@dataclass
class SyclMetadata:
    """SYCL runtime + plugin interface metadata."""
    implementation: str = ""           # "dpcpp" | "adaptivecpp" | "computecpp"
    runtime_version: str = ""          # e.g. "2025.2.0"
    pi_version: str = ""               # PI interface version of the runtime
    plugins: list[SyclPluginInfo] = field(default_factory=list)
    plugin_search_paths: list[str] = field(default_factory=list)
    # Future: SPIR-V module metadata for device-code compat
```

Stored on `AbiSnapshot` as `sycl: SyclMetadata | None` — same pattern as
`elf`, `pe`, `macho`.

### 2. New extraction module: `sycl_metadata.py`

**Static extraction** (no runtime needed):
- Parse PI plugin `.so` files to extract exported `pi*` symbols
- Detect PI version from symbol presence heuristics or version strings
- Inventory plugin libraries in known search paths
- Extract plugin search-path configuration from env/config files

**Optional runtime probing** (requires SYCL runtime):
- Call `piPluginInit` to get exact PI version and dispatch table
- Use `SYCL_PI_TRACE=2` for discovery tracing
- Gated by `requires_support` — disabled when runtime unavailable

### 3. New detector: `diff_sycl.py`

Registered via `@registry.detector("sycl", requires_support=...)`.

Detects:
- PI version mismatch between runtime and plugins
- PI entry points removed from plugin dispatch tables
- Plugins removed from distribution
- Plugin search path changes
- Backend availability changes

### 4. New change kinds (registered in `change_registry.py`)

| ChangeKind | Default verdict | Impact |
|------------|----------------|--------|
| `sycl_pi_version_changed` | BREAKING | Runtime rejects plugins with incompatible PI version |
| `sycl_pi_entrypoint_removed` | BREAKING | Plugin dispatch table missing required function; runtime crashes |
| `sycl_pi_entrypoint_added` | COMPATIBLE | New PI capability; existing code unaffected |
| `sycl_plugin_removed` | BREAKING | Backend no longer available; apps targeting it fail |
| `sycl_plugin_added` | COMPATIBLE | New backend available |
| `sycl_plugin_search_path_changed` | COMPATIBLE_WITH_RISK | Plugins may not be found in new location |
| `sycl_runtime_version_changed` | COMPATIBLE | Informational; actual breaks caught by symbol/type diffs |
| `sycl_backend_driver_req_changed` | COMPATIBLE_WITH_RISK | Newer driver required; may fail on older systems |

### 5. Environment matrix model (generic, reusable)

```python
@dataclass
class EnvironmentMatrix:
    """Declared deployment constraints — shared across SYCL, CUDA, etc."""
    # Host toolchain
    compilers: list[str] = field(default_factory=list)       # ["gcc-13", "clang-17"]
    abi_version: str | None = None                           # -fabi-version value
    libstdcxx_dual_abi: str | None = None                    # "cxx11" | "old"

    # SYCL-specific
    sycl_backends: list[str] = field(default_factory=list)   # ["level_zero", "opencl"]
    sycl_implementation: str | None = None                   # "dpcpp"

    # CUDA-specific (future)
    cuda_gpu_architectures: list[str] = field(default_factory=list)  # ["sm_80", "sm_90"]
    cuda_driver_range: tuple[str, str] | None = None         # ("525.0", "580.0")
    cuda_toolkit_version: str | None = None

    # Generic
    target_os: str = "linux"
    target_arch: str = "x86_64"
```

Passed to `compare()` and used by detectors to parameterize verdicts. When
constraints are unspecified, detectors emit conditional results (e.g.,
"breaking if backend X is required").

### 6. Policy integration

Add a new built-in policy profile `sycl_stack` alongside `strict_abi`,
`sdk_vendor`, `plugin_abi`:

- `sycl_pi_entrypoint_removed` → BREAKING (no downgrade)
- `sycl_plugin_removed` → downgraded to COMPATIBLE_WITH_RISK under
  `sdk_vendor` (vendor may intentionally drop backends)
- `sycl_plugin_search_path_changed` → downgraded to COMPATIBLE under
  `plugin_abi`

### 7. Snapshot serialization

`SyclMetadata` serializes to the existing JSON snapshot format with a new
top-level key `"sycl"`. Schema version bumped to 4. Backward-compatible:
older snapshots without `"sycl"` key load with `sycl=None`.

---

## Architecture diagram

```
AbiSnapshot
├── elf: ElfMetadata          ── existing (libsycl.so covered here)
├── pe: PeMetadata            ── existing
├── macho: MachoMetadata      ── existing
├── dwarf: DwarfMetadata      ── existing
├── dwarf_advanced: ...       ── existing
├── sycl: SyclMetadata        ── NEW (PI plugins, versions, search paths)
│   ├── pi_version
│   ├── plugins[]
│   │   ├── SyclPluginInfo (entry_points, pi_version, backend_type)
│   │   └── ...
│   └── plugin_search_paths[]
└── (future) cuda: CudaMetadata

Detectors (registry)
├── "functions"               ── existing
├── "types"                   ── existing
├── "elf"                     ── existing (handles libsycl.so as any .so)
├── "dwarf"                   ── existing
├── "sycl"                    ── NEW (PI version, entry points, plugins)
└── (future) "cuda"

Change Registry
├── func_removed, type_size_changed, ...  ── existing (114+ kinds)
├── sycl_pi_version_changed, ...          ── NEW (8 kinds)
└── (future) cuda_*                       ── future
```

---

## Consequences

### Positive

- SYCL PI-level compatibility checking fills the biggest gap identified in
  the feasibility analysis for heterogeneous stacks.
- `libsycl.so` ABI diffing requires zero new code — existing ELF engine
  handles it.
- The environment matrix model is generic and directly reusable for CUDA
  support later.
- Self-registering detector pattern means SYCL detector is opt-in: when
  `SyclMetadata` is absent, the detector is automatically skipped.

### Negative

- PI interface is implementation-specific (DPC++). Other SYCL implementations
  may use different plugin mechanisms.
- Static PI extraction (parsing exports) is less precise than runtime probing
  (`piPluginInit`). Both modes should be supported.
- SPIR-V device-code compatibility checking is deferred (complex, analogous
  to CUDA PTX/cubin problem).

### Risks

- PI interface may evolve (DPC++ is moving toward Unified Runtime / UR).
  Design should accommodate PI → UR migration path.
- Plugin `.so` files may not ship with debug info, limiting type-level
  analysis to symbol-only mode.

---

## Implementation plan

### Phase 1: Foundation (Sprint 1)

1. Add `SyclMetadata` + `SyclPluginInfo` dataclasses to new
   `sycl_metadata.py`
2. Add `sycl: SyclMetadata | None` field to `AbiSnapshot`
3. Register 8 new SYCL change kinds in `change_registry.py`
4. Add `ChangeKind` enum entries in `checker_policy.py`
5. Bump snapshot schema version to 4

### Phase 2: Static extraction (Sprint 2)

1. Implement `parse_sycl_metadata()` — inventory plugin `.so` files, extract
   `pi*` exports via pyelftools
2. Wire extraction into `dumper.py` pipeline (detect SYCL artifacts alongside
   ELF parsing)
3. Implement `diff_sycl.py` detector with `@registry.detector("sycl")`

### Phase 3: Environment matrix (Sprint 3)

1. Add `EnvironmentMatrix` dataclass (generic)
2. Add `--env-matrix` CLI input (YAML format)
3. Pass matrix through `compare()` to detectors
4. Emit parameterized verdicts when constraints unspecified

### Phase 4: Runtime probing (Sprint 4, optional)

1. Add optional `piPluginInit` runtime probe (gated by flag)
2. Add `SYCL_PI_TRACE` harness for discovery validation
3. Report probe results as evidence tiers alongside static findings

---

## References

- DPC++ Plugin Interface design: https://github.com/intel/llvm/blob/sycl/sycl/doc/design/PluginInterface.md
- DPC++ ABI policy: https://github.com/intel/llvm/blob/sycl/sycl/doc/ABIPolicyGuide.md
- SYCL 2020 specification (Khronos)
- Feasibility analysis: "Feasibility of a Complete C/C++/SYCL/CUDA ABI/API Breakage Scanner"
- ADR-018: Cross-Platform Binary Format Support (pattern reference)
