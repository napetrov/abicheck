# libabigail vs abicheck — Feature Comparison & Gap Analysis

## Executive Summary

**libabigail** is the mature, C++-based ABI analysis framework from Red Hat (hosted on sourceware.org). **abicheck** is a modern Python replacement for the abandoned ABI Compliance Checker (ABICC). Both solve the same core problem — detecting ABI/API breaking changes in shared libraries — but they take substantially different approaches and have different strengths.

**Bottom line:** abicheck already exceeds libabigail in several areas (cross-platform support, output formats, CI integration, AI tooling). libabigail has strengths in kernel ABI analysis, package-level comparison, DWARF-native analysis, and application compatibility checking that represent opportunities for abicheck.

---

## 1. Tool-by-Tool Comparison

### libabigail Tools

| Tool | Purpose | abicheck Equivalent |
|------|---------|---------------------|
| **abidiff** | Compare ABIs of two ELF shared libraries | `abicheck compare` |
| **abidw** | Dump ABI to XML (ABIXML) format | `abicheck dump` (JSON) |
| **abicompat** | Check if an *application* is compatible with a new library version | **No equivalent** |
| **abipkgdiff** | Compare ABIs across RPM/Deb/tar packages | **No equivalent** |
| **kmidiff** | Compare Kernel Module Interfaces between kernel trees | **No equivalent** |
| **abilint** | Validate/lint ABIXML files | **No equivalent** (not needed — JSON schema validation is simpler) |
| **abidb** | ABI database for tracking changes over time | **No equivalent** |

### abicheck-only Tools

| Tool | Purpose | libabigail Equivalent |
|------|---------|----------------------|
| `abicheck compat check` | ABICC drop-in replacement | None |
| `abicheck compat dump` | ABICC XML descriptor dump | None |
| MCP Server (`abicheck-mcp`) | AI agent integration | None |
| Python API (`from abicheck import ...`) | Programmatic access | C++ API only (libabigail.so) |

---

## 2. Input Format Support

| Format | libabigail | abicheck | Notes |
|--------|-----------|----------|-------|
| **ELF** (.so) | Yes | Yes | Both parse ELF binaries |
| **PE** (.dll) | No | Yes | abicheck supports Windows via pefile |
| **Mach-O** (.dylib) | No | Yes | abicheck supports macOS via macholib |
| **DWARF** debug info | Yes (native, deep) | Yes (via pyelftools) | libabigail's DWARF is more mature |
| **BTF** debug info | Yes | No | eBPF/kernel compact debug format |
| **CTF** debug info | Yes | No | Compact C Type Format |
| **ABIXML** (libabigail XML) | Yes (native) | No | libabigail's serialization format |
| **JSON snapshots** | No | Yes | abicheck's serialization format |
| **ABICC Perl dumps** | No | Yes | Legacy compatibility |
| **ABICC XML descriptors** | No | Yes | Legacy compatibility |
| **RPM packages** | Yes (abipkgdiff) | No | Package-level comparison |
| **Deb packages** | Yes (abipkgdiff) | No | Package-level comparison |
| **Tar archives** | Yes (abipkgdiff) | No | Package-level comparison |
| **Linux kernel trees** | Yes (kmidiff) | No | Kernel ABI analysis |
| **Header files** | Yes (--headers-dir) | Yes (-H, --header) | Both use headers for public API filtering |

---

## 3. Debug Information Depth

### libabigail's DWARF approach
- **Native DWARF consumer**: libabigail reads DWARF directly and builds its internal IR from it. DWARF is the *primary* source of type information.
- **No dependency on castxml**: Types come from debug info, not from re-parsing headers.
- **BTF support**: Can read BTF (BPF Type Format), the compact debug format used in Linux kernel eBPF programs.
- **CTF support**: Can read CTF (Compact C Type Format), an alternative to DWARF used in some systems.
- **DWZ support**: Handles DWARF compression/factorization (DWZ tool output).
- **Split debug info**: Handles `.debug` packages and separate debuginfo directories.

### abicheck's approach
- **Header AST primary**: Uses castxml to parse C/C++ headers into an AST. This is the primary source of type/function information.
- **DWARF cross-check**: Uses DWARF as a secondary layer to validate struct layouts, field offsets, alignment, calling conventions.
- **PDB support**: Reads Windows PDB debug info (basic support).
- **No BTF/CTF**: Missing these compact debug formats.

### Key Difference
libabigail can work with **binaries that have no public headers** — it only needs DWARF/BTF/CTF debug info. abicheck *requires* headers for full analysis (can do ELF-only symbol comparison without headers, but loses type-level analysis).

---

## 4. ABI Change Detection

### Categories of Changes

| Change Category | libabigail | abicheck | Notes |
|----------------|-----------|----------|-------|
| **Function added/removed** | Yes | Yes | Both detect |
| **Function signature changed** | Yes | Yes | Both detect |
| **Variable added/removed** | Yes | Yes | Both detect |
| **Variable type changed** | Yes | Yes | Both detect |
| **Struct/class size changed** | Yes | Yes | Both detect |
| **Field added/removed/offset changed** | Yes | Yes | Both detect |
| **Enum member changes** | Yes | Yes | Both detect |
| **Vtable changes** | Yes | Yes | Both detect |
| **Base class changes** | Yes | Yes | Both detect |
| **Symbol binding/visibility** | Yes | Yes | Both detect |
| **SONAME changes** | Yes | Yes | Both detect |
| **DT_NEEDED changes** | Yes | Yes | Both detect |
| **Symbol versioning changes** | Yes | Yes | Both detect |
| **Template parameter changes** | Partial | Yes | abicheck has explicit template_param_type_changed |
| **Const/volatile qualifier changes** | Yes | Yes | Both detect |
| **Access level changes** | Yes | Yes | Both detect |
| **Calling convention changes** | No (indirect) | Yes | abicheck detects via DWARF DW_AT_calling_convention |
| **noexcept changes** | No | Yes | abicheck detects noexcept added/removed |
| **Preprocessor constant changes** | No | Yes | abicheck tracks #define values |
| **RPATH/RUNPATH changes** | No | Yes | abicheck detects rpath/runpath drift |
| **IFUNC introduction/removal** | No | Yes | abicheck detects GNU indirect functions |
| **Mach-O compat_version changes** | No | Yes | macOS-specific |
| **PE-specific changes** | No | Yes | Windows-specific |
| **Struct packing changes** | No | Yes | __attribute__((packed)) drift |
| **Toolchain flag drift** | No | Yes | -fshort-enums, -fpack-struct detection |
| **Reserved field usage** | No | Yes | Detects __reserved fields being put into use |
| **Dependency symbol leak** | No | Yes | Detects changed symbols from libstdc++/libc |

### Change Classification

| Feature | libabigail | abicheck |
|---------|-----------|----------|
| **Categories** | Harmless / Harmful / Incompatible | COMPATIBLE / COMPATIBLE_WITH_RISK / API_BREAK / BREAKING |
| **Granularity** | 2-3 levels | 5 levels (NO_CHANGE, COMPATIBLE, COMPATIBLE_WITH_RISK, API_BREAK, BREAKING) |
| **Redundancy filtering** | Yes (--no-redundant default) | No explicit redundancy filtering |
| **Leaf-change-only mode** | Yes (--leaf-changes-only) | No |
| **Impact analysis** | Yes (--impacted-interfaces) | No |

---

## 5. Output Formats

| Format | libabigail | abicheck |
|--------|-----------|----------|
| **Plain text report** | Yes (default, custom format) | Yes (Markdown) |
| **XML (ABIXML)** | Yes (abidw output) | No |
| **JSON** | No | Yes |
| **SARIF** | No | Yes (GitHub Code Scanning) |
| **HTML** | No | Yes (standalone interactive report) |
| **Markdown** | No | Yes (default) |

---

## 6. Suppression / Filtering

### libabigail suppressions
- **INI-style suppression specification files** with rich syntax
- **Suppression types**: `[suppress_function]`, `[suppress_variable]`, `[suppress_type]`, `[suppress_file]`
- **Matching criteria**: name, name_regexp, name_not_regexp, soname_regexp, return_type_name, parameter, change_kind, has_data_member_inserted_at, etc.
- **Built-in default suppressions** (shipped with the tool)
- **In-package .abignore files** (abipkgdiff auto-detects)
- **KMI whitelists** for kernel symbol filtering

### abicheck suppressions
- **YAML-based suppression files**
- **Matching**: symbol (exact), symbol_pattern (regex), type_pattern, source_location (glob), change_kind
- **Expiry dates**: `expires: 2026-06-01` — suppressions auto-expire
- **Labels**: organizational metadata
- **ABICC compatibility**: skip-symbols, skip-types, whitelist files

### Comparison
- libabigail's suppression syntax is **more granular** (can filter by return type, parameter type, member offset, etc.)
- abicheck's suppressions have **expiry dates** (unique feature — prevents stale suppressions)
- abicheck's YAML format is **more readable** than libabigail's INI format

---

## 7. Unique libabigail Features (Gaps in abicheck)

### 7.1 Application Compatibility Checking (abicompat)
**What it does**: Takes an *application binary* and checks whether it's compatible with a new version of a library it links against. This is the reverse perspective — instead of comparing two library versions, it checks "will my app still work?"

**Why it matters**: Useful for distro maintainers, CI pipelines that test downstream consumers.

**Recommendation**: **HIGH PRIORITY** — Add an `abicheck appcompat` command that takes an application binary and two library versions.

### 7.2 Package-Level Comparison (abipkgdiff)
**What it does**: Compares ABI across RPM, Deb, and tar packages. Automatically extracts binaries, finds matching debug info packages, and compares all shared libraries in parallel.

**Why it matters**: Distro maintainers compare package updates directly without extracting files manually.

**Recommendation**: **MEDIUM PRIORITY** — Add `abicheck pkg-compare` that accepts RPM/Deb/tar/directory inputs. Useful for enterprise/distro users.

### 7.3 Kernel Module Interface Analysis (kmidiff)
**What it does**: Compares the kernel module interface (KMI) between two Linux kernel trees. Uses vmlinux + modules + KMI whitelists.

**Why it matters**: Critical for enterprise Linux distros (RHEL, SUSE) that maintain stable kABI.

**Recommendation**: **LOW-MEDIUM PRIORITY** — Niche use case, but high value for enterprise Linux. Consider as a future extension.

### 7.4 BTF Debug Format Support
**What it does**: BTF (BPF Type Format) is a compact debug format used in the Linux kernel, particularly for eBPF programs. libabigail can read ABI from BTF.

**Why it matters**: Growing importance with eBPF ecosystem. BTF is much smaller than DWARF.

**Recommendation**: **MEDIUM PRIORITY** — Add BTF reader. The `btftools` or `pahole` ecosystem could provide parsing support.

### 7.5 CTF Debug Format Support
**What it does**: CTF (Compact C Type Format) is an alternative to DWARF, more compact.

**Why it matters**: Used in some systems (Solaris/illumos heritage, some Linux builds).

**Recommendation**: **LOW PRIORITY** — Less common than BTF. Consider after BTF.

### 7.6 Redundancy Filtering
**What it does**: libabigail suppresses "redundant" changes by default — if a type change is reported for one function, it doesn't repeat it for every other function using that type.

**Why it matters**: Reports can be much cleaner. A single struct change that affects 50 functions is shown once, not 50 times.

**Recommendation**: **HIGH PRIORITY** — Add `--no-redundant` (default on) to deduplicate type changes across multiple symbols.

### 7.7 Leaf-Change-Only Mode
**What it does**: `--leaf-changes-only` shows only the actual type modifications, without the full chain of impacted interfaces. Combined with `--impacted-interfaces`, it can show "this struct changed" + "these 15 functions are affected".

**Why it matters**: Much more readable reports for large libraries with many type changes.

**Recommendation**: **MEDIUM PRIORITY** — Add `--leaf-changes` and `--show-impact` flags.

### 7.8 DWARF-Only Analysis (No Headers Required)
**What it does**: libabigail can do full type-level ABI comparison using *only* DWARF debug info — no headers needed.

**Why it matters**: Many binaries ship with debuginfo but not headers. Distro maintainers often have debuginfo packages but not -devel packages installed.

**Recommendation**: **HIGH PRIORITY** — Enhance DWARF metadata extraction to provide full type information without requiring castxml/headers. This would remove the castxml dependency for many use cases.

### 7.9 Corpus Groups (Multi-Binary Analysis)
**What it does**: libabigail can analyze multiple binaries together as a "corpus group" — e.g., all `.so` files in a library suite.

**Why it matters**: Libraries like GLib ship multiple `.so` files that form a coherent API.

**Recommendation**: **MEDIUM PRIORITY** — Add `abicheck compare --group dir1/ dir2/` for multi-binary comparison.

### 7.10 Dependency-Aware Comparison
**What it does**: `--follow-dependencies` makes abidiff also compare the shared library's dependencies.

**Why it matters**: A library's ABI can break not just from its own changes but from changes in its dependencies.

**Recommendation**: **LOW-MEDIUM PRIORITY** — abicheck already detects `symbol_leaked_from_dependency_changed` but doesn't do full dependency comparison.

---

## 8. Unique abicheck Features (Advantages Over libabigail)

| Feature | Details |
|---------|---------|
| **Cross-platform** | ELF + PE + Mach-O (libabigail is ELF-only) |
| **113 change kinds** | More granular than libabigail's categories |
| **5 verdict levels** | More nuanced than libabigail's harmless/harmful binary |
| **Policy system** | Built-in policies (strict_abi, sdk_vendor, plugin_abi) + custom YAML |
| **4 output formats** | Markdown, JSON, SARIF, HTML (libabigail: text + XML) |
| **SARIF / GitHub Code Scanning** | Direct CI integration |
| **HTML reports** | Self-contained interactive reports |
| **Suppression expiry dates** | Auto-expiring suppressions prevent stale exceptions |
| **MCP Server** | AI agent integration (Claude, Cursor, etc.) |
| **Python API** | Easy programmatic access |
| **ABICC compatibility** | Drop-in replacement mode |
| **PDB debug info** | Windows debug info support |
| **Preprocessor constant tracking** | Detects #define value changes |
| **RPATH/RUNPATH detection** | Detects runtime library path changes |
| **IFUNC detection** | Detects GNU indirect function introduction |
| **Calling convention drift** | DWARF-based calling convention detection |
| **Struct packing detection** | __attribute__((packed)) changes |
| **Toolchain flag drift** | -fshort-enums, -fpack-struct detection |
| **Reserved field usage** | Detects __reserved fields being repurposed |
| **Snapshot workflow** | Save/load/compare JSON baselines |

---

## 9. Prioritized Recommendations

### Tier 1 — High Impact, Fills Major Gaps

| # | Feature | Effort | Impact | Details |
|---|---------|--------|--------|---------|
| 1 | **Redundancy filtering** | Medium | High | Deduplicate type changes across symbols. A struct change affecting 50 functions should appear once. Add `--no-redundant` (default on). |
| 2 | **DWARF-only analysis mode** | High | High | Full ABI comparison from DWARF alone, no headers/castxml required. Dramatically broadens use cases. |
| 3 | **Application compat check** | Medium | High | `abicheck appcompat <app> <old-lib> <new-lib>` — check if an application binary remains compatible with a library update. |
| 4 | **Leaf-change + impact mode** | Medium | High | `--leaf-changes` shows only root type modifications; `--show-impact` lists affected interfaces. Cleaner reports for large diffs. |

### Tier 2 — Medium Impact, Broadens Audience

| # | Feature | Effort | Impact | Details |
|---|---------|--------|--------|---------|
| 5 | **Package-level comparison** | High | Medium | `abicheck pkg-compare old.rpm new.rpm` — compare all binaries in RPM/Deb/tar packages. Critical for distro maintainers. |
| 6 | **BTF debug format** | Medium | Medium | Read ABI from BTF. Important for eBPF and kernel ecosystem. |
| 7 | **ABIXML import** | Low | Medium | Read libabigail's ABIXML format as input, enabling migration from libabigail pipelines. |
| 8 | **Corpus groups** | Medium | Medium | `abicheck compare --group dir1/ dir2/` for multi-binary library suites. |

### Tier 3 — Lower Priority, Nice-to-Have

| # | Feature | Effort | Impact | Details |
|---|---------|--------|--------|---------|
| 9 | **Kernel ABI (kABI) analysis** | High | Low-Med | `abicheck kabi-diff` for kernel module interface comparison. Enterprise Linux niche. |
| 10 | **CTF debug format** | Medium | Low | Read ABI from CTF. Less common than BTF. |
| 11 | **Dependency-aware comparison** | Medium | Low-Med | `--follow-dependencies` to compare transitive dependency ABIs. |
| 12 | **In-package suppression files** | Low | Low | Auto-detect `.abignore`-style files in packages/directories. |

---

## 10. Exit Code Comparison

| Condition | libabigail | abicheck |
|-----------|-----------|----------|
| Success / no change | 0 | 0 |
| Tool error | 1 (ABIDIFF_ERROR) | 1 |
| Usage error | 2 (ABIDIFF_USAGE_ERROR) | — |
| ABI change (compatible) | 4 (ABIDIFF_ABI_CHANGE) | 0 |
| ABI incompatible change | 8 (ABIDIFF_ABI_INCOMPATIBLE_CHANGE) | 4 (BREAKING) |
| API break | — | 2 (API_BREAK) |

Note: libabigail uses **bitmask** exit codes (can be OR'd: 4|8 = 12). abicheck uses **distinct** exit codes.

**Recommendation**: Consider adding a `--libabigail-exit-codes` flag for compatibility with scripts that parse libabigail exit codes.

---

## 11. Architecture Comparison

### libabigail
```
ELF binary + DWARF/BTF/CTF
       │
       ▼
  DWARF/BTF/CTF Reader (C++)
       │
       ▼
  Internal IR (abigail::ir)
       │
       ▼
  Comparison Engine (abigail::comparison)
       │
       ▼
  Text Report / ABIXML
```

- Written in C++ (~150k LOC)
- Reads DWARF natively (no external parser)
- Internal IR is a rich type graph
- Single-platform (ELF/DWARF focus)

### abicheck
```
Binary (ELF/PE/Mach-O) + Headers + Debug Info
       │                     │            │
       ▼                     ▼            ▼
  Binary Parser         castxml AST    DWARF/PDB
  (pyelftools/          (XML → model)  (pyelftools/
   pefile/macholib)                     pdb_parser)
       │                     │            │
       ▼                     ▼            ▼
       └─────── AbiSnapshot (JSON) ───────┘
                      │
                      ▼
              Checker (113 change kinds)
                      │
                      ▼
              Verdict + Report (MD/JSON/SARIF/HTML)
```

- Written in Python (~14k LOC)
- Multi-platform binary support
- Header AST is primary type source
- Snapshot-based workflow enables offline comparison
- Multiple output formats

---

## 12. Summary Matrix

| Dimension | libabigail | abicheck | Winner |
|-----------|-----------|----------|--------|
| **Platform coverage** | ELF only | ELF + PE + Mach-O | abicheck |
| **Debug format breadth** | DWARF + BTF + CTF | DWARF + PDB | libabigail |
| **Headers required?** | No (DWARF-only works) | Yes (for full analysis) | libabigail |
| **Change detection granularity** | ~30 categories | 113 explicit kinds | abicheck |
| **Verdict nuance** | 2-3 levels | 5 levels | abicheck |
| **Output formats** | Text + XML | MD + JSON + SARIF + HTML | abicheck |
| **Suppression power** | Very granular (type/param matching) | Expiry dates, YAML, simpler | Tie |
| **Package comparison** | RPM/Deb/tar | None | libabigail |
| **Kernel ABI** | Full (kmidiff) | None | libabigail |
| **App compat check** | Yes (abicompat) | None | libabigail |
| **Report readability** | Verbose text | Clean markdown/HTML | abicheck |
| **CI/CD integration** | Basic (exit codes) | SARIF + GitHub Action | abicheck |
| **AI integration** | None | MCP Server | abicheck |
| **Python API** | None (C++ only) | Full | abicheck |
| **ABICC compat** | None | Drop-in replacement | abicheck |
| **Performance** | Fast (C++) | Slower (Python + castxml) | libabigail |
| **Maturity** | 10+ years, battle-tested | Newer | libabigail |
| **Accuracy** | Good (26% on abicheck test suite) | Excellent (100% on test suite) | abicheck |
