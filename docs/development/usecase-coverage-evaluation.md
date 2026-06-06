# Use-Case Coverage Evaluation

**Date:** 2026-05-30
**Purpose:** Evaluate abicheck against the full landscape of application/library
ABI-API change use cases, identify where coverage is deep vs. thin, and record
the concrete code / test / example follow-ups.

This is a companion to [`adr/adr-gap-analysis.md`](adr/adr-gap-analysis.md)
(which tracks *undocumented decisions*); this document tracks *uncovered
scenarios*.

Three related artifacts, kept distinct: the **examples catalog** (`examples/`)
demonstrates ABI/API *change types*; the **user-scenario catalog**
([User Scenarios & Flows](user-scenarios.md), `tests/scenarios/`) defines *how
users work with abicheck* and drives end-to-end *tool* validation; and the
[plans](plans/index.md) track the *capability backlog*. This document is the
map across all three.

---

## Headline

abicheck is **exceptionally deep on the change-taxonomy axis and comparatively
thin on the breadth axes.** The "what changed" dimension — **189 `ChangeKind`s**
in a 5-tier policy model, **121 calibrated example cases**, ABICC + libabigail
parity — is essentially complete and has diminishing returns.

The remaining gaps are **not in detecting more change types**. They are in
**breadth across platforms, workflows, and consumption topologies**:

1. Cross-platform support: the core `compare` workflow is now **validated
   end-to-end on native PE/Mach-O** in the `cross-platform-e2e` CI lane (G1
   closed). What remains Linux-anchored is the *example catalog* — most
   workflow fixtures run on Linux, and `macos`/`windows` `platforms` tags mark
   intended portability rather than a per-case CI result.
2. The build-configuration matrix is **siloed in a separate `probe` command**
   disconnected from `compare` / `compare-release`.
3. The example catalog is **almost entirely single-pair `compare` fixtures** —
   the other workflows (`appcompat`, `deps`/`stack-check`, `bundle`, `probe`)
   are unit-tested with synthetic snapshots, not driven by catalog fixtures.

---

## The use-case universe (five axes)

A real invocation is a point in this space:

| Axis | Values |
|---|---|
| **Library archetype** | pure-C system lib · C++ template/vtable lib · header-only/inline · plugin (dlopen) · static (`.a`) · kernel/eBPF · GPU/accelerator (SYCL/CUDA) · FFI-consumed C ABI |
| **Platform** | ELF/Linux · PE+PDB/Windows (MSVC, MinGW) · Mach-O/macOS (x86-64, ARM64) |
| **Change class** | binary ABI break · source API break · compatible addition · quality/bad-practice · deployment risk |
| **Workflow** | CI PR gate · release/package compare · baseline pin · app-compat · multi-lib bundle · build-config matrix · stack/sysroot · Debian symbols · ABICC drop-in · MCP/agent |
| **Toolchain/standard** | GCC/Clang/MSVC/ICX · C++11→23 floor · libstdc++ dual ABI · flag drift · LP64/ILP64 · char8_t/_BitInt/atomic/ABI-tags |

## Coverage scorecard

> **The authoritative, machine-checked status of every use case lives in
> [`usecase-registry.yaml`](usecase-registry.yaml)**, validated by
> `tests/test_usecase_registry.py` (it enforces that coverage claims cite
> evidence paths that actually exist, and that unfinished items carry a tracked
> gap + next steps). The table below is a human snapshot; statuses use the
> registry's vocabulary:
> `complete` · `partial` · `modeled` (code exists, not validated end-to-end) ·
> `planned` · `by_design_excluded`.

| Use case | Status | Notes |
|---|---|---|
| Change taxonomy | `complete` | 189 kinds; 121 cases; parity tests |
| **Release recommendation (semver + SONAME)** | `complete` | **added in this change** |
| C / C++ archetypes | `complete` | 35 C + 52 C++ example pairs |
| Linux ELF platform | `complete` | the CI-validated baseline |
| Windows PE/MSVC | `complete` | **G1 closed**: `cross-platform-e2e` lane runs `compare` on MinGW DLLs; MSVC+PDB lane asserts struct-growth + removed-export verdicts |
| macOS Mach-O/ARM64 | `complete` | **G1 closed**: `cross-platform-e2e` lane runs `compare` on Apple-clang dylibs; AAPCS64 HFA/HVA + 16-byte boundary modeled + unit-tested |
| `compare`/release/baseline/Debian/ABICC | `complete` | dedicated CLIs + tests |
| MCP server | `complete` | unit-tested (mocks, Linux) |
| Reporting: JSON/SARIF/JUnit | `complete` | versioned schema + 34 SARIF / 55 JUnit tests |
| Reporting: Markdown/HTML | `complete` | structural coverage across verdict tiers + sections + escaping (G3 done) |
| Build-config matrix (`probe`) | `complete` | **G2 closed**: wired into `compare`; both CXX floor and API_DEPENDS proven e2e (`.o` `.symtab` surface capture fixed) |
| Bundle / multi-library | `complete` | all detectors run via `compare-release`; case84 validated e2e (Linux-only by design; cross-platform → G1) |
| Plugin (host↔plugin) | `complete` | **G5 closed**: `plugin-check` CLI + `check_plugin_host_contract` API + plugin_abi policy |
| Security-hardening drift | `complete` | **G12 closed**: full checksec surface (RELRO/BIND_NOW/PIE/canary/FORTIFY/W^X) diffed; shipped `--policy-file security` gate |
| Header-only / inline-only | `planned` | castxml can't emit concept bodies / ctor mangled names (G4; cases 78/105/106/111 dormant) |
| Kernel / eBPF (BTF/CTF) | `complete` | **G6 closed**: BTF + CTF struct-change run through `compare`; committed `case121` BTF blobs + bare-blob CLI ingestion + `gcc -gbtf` integration fixture |
| SYCL / accelerator (PI/UR) | `complete` | **G6 closed**: PI *and* UR adapter entrypoint-drop driven through `compare` + reports |
| Static libraries (`.a`/`.lib`) | `by_design_excluded` | **G8 decided (option A)**: non-goal; CLI rejects archives with guidance |
| FFI consumers (Rust/Go/Python) | `by_design_excluded` | C ABI covered; other languages a stated non-goal |

---

## Gaps that matter — and what each needs

| ID | Gap | Code | Tests | Examples |
|---|---|:--:|:--:|:--:|
| **G1** | ✅ **closed** — native PE/Mach-O `compare` validated in CI (`cross-platform-e2e` lane) + AAPCS64 modeling | ✅ `classify_aapcs64_aggregate`; broadened MSVC+PDB lane | ✅ native binary↔binary compare verdicts (clang/MinGW) | catalog tags stay a Linux subset (by design) |
| **G2** | Build-config matrix siloed in `probe` | ✅ folded into `compare`/`compare-release` (`--probe-matrix-old/new`); bundle soname-skew wired; `.o` `.symtab` surface capture | ✅ CXX floor + API_DEPENDS e2e + case84 bundle e2e | ✅ `feature_macro.yaml`, `cxx_standard.yaml` |
| **G3** | Catalog only exercises `compare`; Markdown/HTML test coverage thin | — | ✅ appcompat-from-catalog + stack-check sysroot e2e + Markdown/HTML structural coverage | scenarios asserted in new tests |
| **G4** | Header-only / inline-only (detector frontier) | libclang header-AST extractor | unblock cases 78/105/106/111 | reuse dormant fixtures |
| **G5** | Plugin host↔plugin contract is one-directional | ✅ `check_plugin_host_contract` + `plugin-check` CLI | ✅ scenario + CLI tests | compiled host/plugin demo optional |
| **G6** | ✅ **closed** — kernel/eBPF + accelerator workflows | ✅ BTF/CTF/SYCL(PI+UR) run through `compare`; bare-blob CLI ingestion | ✅ workflow scenarios + `gcc -gbtf` integration | ✅ committed `case121` BTF-blob example |
| **G7** | No semver-bump recommendation | recommender + report wiring | mapping + integration | reuse cases |
| **G8** | Static libraries undocumented | ✅ archive detection + clear error path | ✅ unit (archive → guidance error) | ✅ documented non-goal (goals + limitations) |

### Gaps added from empirical scanning (G9–G15)

A later pass ran abicheck against real open-source binaries (distro `.so`,
manylinux wheels + their vendored stack, static archives) and surfaced these
*topology/workflow* gaps now tracked in the registry. G14–G15 were added after a
43-wheel empirical scan (two releases each of popular C-extension packages):

| ID | Gap | Registry use case | Plan |
|---|---|---|---|
| **G9** | auditwheel/manylinux vendored libs never pair (content-hash sonames change every rebuild) | `UC-WF-wheel-vendored` | [g9](plans/g9-wheel-vendored-matching.md) |
| **G10** | no manylinux glibc-floor / platform-baseline check (data captured, no detector) | `UC-TC-glibc-floor` | [g10](plans/g10-glibc-floor-check.md) |
| **G11** | no single-binary audit/lint mode (every command is comparative) | `UC-WF-audit` | [g11](plans/g11-single-binary-audit.md) |
| **G12** | ✅ **closed** — full checksec surface (RELRO/BIND_NOW/PIE/canary/FORTIFY/W^X) captured + diffed; shipped `--policy-file security` gate | `UC-WF-security-hardening` | [g12](plans/g12-security-hardening.md) |
| **G13** | no cross-architecture guardrail (x86-64 vs aarch64 reports false-green) | `UC-PLAT-arch-guard` | [g13](plans/g13-arch-mismatch-guard.md) |
| **G14** | abi3 wheel compatibility lives in *imported* CPython symbols, not exports — never checked (cryptography 42→43 stays COMPATIBLE while +7 `Py*` imports appear) | `UC-WF-stable-abi-subset` | [g14](plans/g14-stable-abi-subset.md) |
| **G15** | inline-namespace version stamp makes every symbol churn (ICU 73→74: 6288 phantom changes vs a real +34/−0) | `UC-CHANGE-inline-ns-version` | [g15](plans/g15-inline-namespace-version.md) |

The 43-wheel scan also reproduced **G9 at scale**: every package that vendors a
stack hit the phantom removed+added failure — 42 phantom pairs total, led by
Pillow (15), opencv-python (14), psycopg2-binary (5) — and exposed a *false
negative* (pyzmq's bundled `libsodium` `SONAME 23→26` hidden as removed+added).
None of these require new change-*type* detection; G9 and G14 are the two
highest-value.

### Answer to the four driving questions

1. **How does abicheck handle these configurations?** Superbly for *change-type
   detection on Linux via `compare`*; partially-to-aspirationally for
   *Windows/macOS, build-config-dependent APIs, plugin/kernel topologies, and
   "what should I version-bump?"*.
2. **Code changes needed?** Yes, but mostly **breadth/integration**, not new
   detectors: semver output (S, **done here**), probe-into-compare wiring (M),
   plugin contract (M), ARM64/MSVC fidelity (L), libclang AST (XL).
3. **More tests?** **The most clearly justified item** — cross-platform e2e and
   workflow-level (non-`compare`) tests.
4. **Examples worth adding?** Yes, but of a **different kind** — the catalog is
   saturated with change-*types*; the high-value additions are
   *workflow/topology* scenarios (plugin pair, kernel BTF, probe matrix,
   appcompat/stack scenarios) and **native PE/Mach-O fixtures**.

---

## What is implemented vs. planned

To be unambiguous: this work **fully implemented one cell** (the semver/SONAME
recommender), **partially advanced two** (the plugin contract — via scenario
tests; cross-platform — via an honesty doc + guard), and **left the rest as
tracked plans** (`planned`/`partial`/`modeled` rows in
[`usecase-registry.yaml`](usecase-registry.yaml), each with a gap id and
`next_steps`). Nothing else from the scorecard was silently "finished" — the
registry test would fail if a status claimed evidence that did not exist.

### Implemented in this change

This PR lands the highest value-per-effort slice and the scaffolding for the
rest:

- **G7 — Release recommender** (`abicheck/semver.py`): maps the policy-aware
  verdict + change set to a recommended **semver bump** (`major`/`minor`/
  `patch`/`none`) and a **SONAME action** (`bump_required`/`bump_performed`/
  `bump_missing`/`no_bump_needed`). Always present in `--format json` under
  `release_recommendation`; opt-in for Markdown via `--recommend`. Unit-tested
  in `tests/test_semver_recommendation.py`.
- **G3 / G5 — Workflow-scenario tests** (`tests/test_workflow_scenarios.py`):
  drop-in upgrade gate, additive minor release, host↔plugin load contract (both
  directions of "does this drop break *this* consumer"), and a policy-scoped
  release decision — covering topologies that `compare` alone does not express.
- **G1 — Cross-platform honesty**: the platform-support reality (Linux =
  CI-validated baseline; Windows/macOS = parser-level, partial) is stated in
  [`reference/platforms.md`](../reference/platforms.md) and guarded by
  `tests/test_platform_coverage_honesty.py`, which enforces that every example
  case supports the Linux baseline and that Windows/macOS remain a strict
  subset.

## Proposed next steps (tracked, not in this change)

> **Detailed, actionable plans for every remaining item live in
> [`plans/`](plans/index.md)** — one per gap, each with goal, acceptance
> criteria, design, files to touch, test plan, and effort. Each `partial` /
> `modeled` / `planned` entry in [`usecase-registry.yaml`](usecase-registry.yaml)
> links its plan via a `plan:` field that the registry test verifies exists.

Summary (see the plans for detail):

- **G1 (CI):** add Windows (MinGW) and macOS smoke jobs that run `compare` /
  `appcompat` on a handful of native PE/Mach-O fixtures; promote the most
  reliable `known_gap` cases to validated once green.
- **G2 (closed):** matrix findings fold into `compare`/`compare-release` via
  `--probe-matrix-old/--probe-matrix-new`. Both `CXX_STANDARD_FLOOR_RAISED` and
  `API_DEPENDS_ON_CONSUMER_ENV` now fire end-to-end through the mainline command
  — the latter unblocked by capturing a relocatable probe `.o`'s symbol surface
  (`parse_elf_metadata` falls back to `.symtab` when there is no `.dynsym`).
- **G4:** a libclang-based header-AST extractor alongside castxml to unblock
  concept tightening, hidden friends, and user-ctor mangled names (cases
  78/105/106/111).
- **G6 (advanced):** the BTF struct-change and SYCL entrypoint-drop workflows
  now run through `compare` end-to-end (real BTF bytes parsed by
  `parse_btf_from_bytes`; SYCL findings reach the JSON/Markdown reports) in
  `tests/test_workflow_kernel_accel.py`, documented in
  [`user-guide/kernel-btf.md`](../user-guide/kernel-btf.md). Remaining: a
  committed BTF-blob example under `examples/` with a `ground_truth.json` entry
  (and a `pahole`/`bpftool` integration fixture); CTF and a UR-adapter workflow
  are still open.

**G8 is now decided (option A — done):** static/import library archives are a
non-goal. `abicheck/binary_utils.py::detect_archive` recognises the `!<arch>\n`
magic and `service.resolve_input` rejects `.a`/`.lib` inputs with actionable
guidance; the stance is documented in [`goals.md`](goals.md) (Non-goals) and
[`concepts/limitations.md`](../concepts/limitations.md), and the registry entry
is `by_design_excluded`.
