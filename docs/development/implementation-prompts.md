# Implementation Prompts for Smaller Features

These features extend existing patterns and don't require separate ADRs. Each
section is a self-contained prompt you can hand to a session for implementation.

---

## 1. JUnit XML Output

**Extends:** ADR-014 (Output Format Strategy)
**Complexity:** S (1-2 days)
**Why no ADR:** Follows the established reporter pattern — no architectural decisions.

### Prompt

Implement JUnit XML output for abicheck. This enables GitLab CI, Jenkins, Azure
DevOps, and other CI systems to display ABI check results as "test results" in
their standard dashboards.

**What to build:**

1. New file: `abicheck/junit_report.py`
2. New CLI flag: `--format junit` (add to both `compare` and `compare-release`)
3. Map ABI changes to JUnit test cases using this scheme:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="abicheck" tests="47" failures="3" errors="0" time="1.23">
  <testsuite name="libfoo.so.1" tests="47" failures="3">
    <!-- Each exported symbol is a "test case" -->
    <testcase name="_ZN3foo3barEv" classname="functions">
      <!-- Pass: no ABI change detected -->
    </testcase>

    <testcase name="_ZN3foo3bazEi" classname="functions">
      <failure message="func_param_type_changed: parameter 1 type changed from int to long"
               type="BREAKING">
Parameter 1 of foo::baz changed from int (4 bytes) to long (8 bytes).
This is a binary-incompatible change.
Source: include/foo.h:42
      </failure>
    </testcase>

    <testcase name="struct foo::Config" classname="types">
      <failure message="type_size_changed: size changed from 16 to 24 bytes"
               type="BREAKING">
struct foo::Config size changed from 16 to 24 bytes.
Field 'new_field' was added at offset 16.
      </failure>
    </testcase>

    <!-- Removed symbols are failures -->
    <testcase name="_ZN3foo6legacyEv" classname="functions">
      <failure message="func_removed" type="BREAKING">
Function foo::legacy() was removed from the exported interface.
      </failure>
    </testcase>

    <!-- Added symbols are passing tests (info only) -->
    <testcase name="_ZN3foo9new_thingEv" classname="functions">
      <!-- Pass: addition is compatible -->
    </testcase>
  </testsuite>
</testsuites>
```

**Mapping rules:**
- Each library in a `compare-release` is a `<testsuite>`
- Each exported symbol/type that was checked is a `<testcase>`
- `classname` groups: `functions`, `variables`, `types`, `enums`, `metadata`
- Changes with verdict BREAKING or API_BREAK → `<failure>`
- Changes with verdict COMPATIBLE_WITH_RISK → `<failure>` if severity is `error`, else pass
- COMPATIBLE changes → pass (the test case exists but has no `<failure>` child)
- `type` attribute: the verdict level (`BREAKING`, `API_BREAK`, `COMPATIBLE_WITH_RISK`)
- `message` attribute: `change_kind: one-line summary`
- Body text: detailed explanation + source location if available

**Implementation notes:**
- Use `xml.etree.ElementTree` (stdlib) — no external dependency needed
- Follow the existing reporter pattern: function takes `DiffResult` → returns `str`
- Register in `cli.py` alongside existing format options
- Handle `compare-release` by creating multiple `<testsuite>` elements
- Escape XML entities in symbol names (C++ mangled names can contain `<>`)
- Include timing info from `DiffResult.duration_ms` if available
- The `tests` count should include ALL checked symbols (not just changed ones), so
  the pass rate is meaningful. Get total from `old_snapshot.functions` + `old_snapshot.types` etc.

**Tests to write:**
- Unit test: `test_junit_report.py` — verify XML structure for known DiffResult
- Test with no changes → all `<testcase>` pass, zero failures
- Test with BREAKING changes → correct `<failure>` elements
- Test with suppressed changes → suppressed symbols still appear as passing
- Test XML escaping of C++ mangled names with templates
- Integration: run `abicheck compare --format junit` on example cases, validate XML schema

---

## 2. GitHub PR Annotations

**Extends:** ADR-017 (GitHub Action Design)
**Complexity:** S (half day)
**Why no ADR:** Minor enhancement to existing GitHub Action output.

### Prompt

Add GitHub workflow command annotations to abicheck's output when running in
GitHub Actions. This makes ABI breaking changes appear as inline annotations
on PR diffs.

**What to build:**

1. New function in `abicheck/reporter.py` (or new file `abicheck/annotations.py`):
   `emit_github_annotations(diff_result: DiffResult) -> str`
2. Auto-detect GitHub Actions via `GITHUB_ACTIONS=true` environment variable
3. Emit annotations to stdout using GitHub's workflow command syntax

**Format:**

```text
::error file=include/foo.h,line=42,title=ABI Break: func_param_type_changed::Parameter 1 of foo::baz changed from int to long (binary incompatible)
::warning file=include/foo.h,line=15,title=API Break: func_removed::Function foo::legacy() was removed
::notice title=ABI Addition: func_added::Function foo::new_thing() was added to the public interface
```

**Mapping:**
- BREAKING changes → `::error`
- API_BREAK / COMPATIBLE_WITH_RISK changes → `::warning`
- Additions / COMPATIBLE → `::notice` (only if `--annotate-additions` flag is set, off by default)
- `file` and `line` are only emitted when `change.source_location` is available
- `title` includes the change kind for quick scanning
- Message body is a one-line summary (workflow commands don't support multiline well)

**CLI integration:**
- `--annotate` flag on `compare` and `compare-release` commands
- When `GITHUB_ACTIONS=true` and `--annotate` is set, emit annotations to stdout
  BEFORE the normal report output
- Limit to top 50 annotations (GitHub caps at ~50 visible per step)
- Sort by severity (BREAKING first) to ensure most important annotations are visible

**Implementation notes:**
- Keep it simple: just string formatting, no external dependencies
- Escape special characters in messages (`:`, `,` in values)
- When source location is not available (symbols-only mode), omit `file` and `line`
- Consider also emitting a job summary via `$GITHUB_STEP_SUMMARY` (Markdown format,
  which abicheck already produces)

**Tests:**
- Unit test: verify annotation format for known changes
- Test annotation count limit (50 max)
- Test with and without source locations
- Test escaping of special characters

---

## 3. Suppression Lifecycle Enforcement

**Extends:** ADR-013 (Suppression System Design)
**Complexity:** S-M (1-2 days)
**Why no ADR:** Builds directly on existing suppression model with expiry/audit.

### Prompt

Enhance abicheck's suppression system with CI enforcement features: fail on expired
suppressions, auto-suggest suppressions from diffs, and require justification strings.

**What to build:**

### 3a. Fail on expired suppressions (`--strict-suppressions`)

Add `--strict-suppressions` flag to `compare` and `compare-release`. When set:
- Load suppression file normally
- Check all rules for expiry via existing `is_expired()` method
- If ANY rule is expired, fail with exit code 1 and message:

```text
ERROR: 2 expired suppression rules found in suppressions.yml:
  Rule 2: symbol_pattern="_ZN3foo.*Internal.*" expired on 2026-01-15
  Rule 5: symbol="_ZN3bar6legacyEv" expired on 2026-03-01

Remove or renew expired rules before proceeding.
Use --renew-suppressions to extend expiry dates interactively.
```

This prevents stale suppressions from silently hiding regressions.

### 3b. Require justification strings (`--require-justification`)

Add `--require-justification` flag. When set:
- Validate that every suppression rule has a non-empty `reason` field
- Fail at load time if any rule lacks a reason:

```text
ERROR: Suppression rule 3 has no 'reason' field.
All suppression rules must include a justification when --require-justification is set.
```

### 3c. Auto-suggest suppressions (`abicheck suggest-suppressions`)

New CLI command that takes a diff result and generates candidate suppression rules:

```bash
abicheck compare old.so new.so -H include/ --format json -o diff.json
abicheck suggest-suppressions diff.json -o candidates.yml
```

Output (`candidates.yml`):

```yaml
# Auto-generated suppression candidates from abicheck compare
# Review each rule and add a justification before using
suppressions:
  - symbol: "_ZN3foo6legacyEv"
    change_kind: func_removed
    reason: ""  # TODO: add justification
    expires: "2026-09-23"  # 6 months from generation date

  - symbol: "_ZN3foo3bazEi"
    change_kind: func_param_type_changed
    reason: ""  # TODO: add justification
    expires: "2026-09-23"
```

Default expiry: 6 months from generation (configurable via `--expiry-days N`).

**Implementation notes:**
- `--strict-suppressions` is a simple pre-check in the compare pipeline, after
  loading the suppression file but before applying it
- `--require-justification` is validation in `SuppressionList.load()`
- `suggest-suppressions` reads a JSON diff result and maps changes to rules
- For `suggest-suppressions`, prefer exact symbol match over patterns (safer)
- Generate `type_pattern` rules for type-level changes
- Include `# TODO` comments in YAML output to flag unreviewed rules

**Tests:**
- Test `--strict-suppressions` with expired and non-expired rules
- Test `--require-justification` with missing and present reasons
- Test `suggest-suppressions` output for various change kinds
- Test default expiry calculation

---

## 4. ELF Symbol-Version Policy Checks

**Extends:** ADR-011 (Change Classification Taxonomy), existing detectors
**Complexity:** M (2-3 days)
**Why no ADR:** Extends existing L0 detector pattern with new ChangeKinds.

### Prompt

Add policy-level checks for ELF symbol versioning that go beyond detecting changes
to enforcing version-bump rules and emitting actionable guidance.

**What to build:**

### 4a. New ChangeKinds

Add these to `change_registry.py`:

| ChangeKind | Severity | Description |
|------------|----------|-------------|
| `symbol_version_node_removed` | abi_breaking | A version node (e.g., `LIBFOO_1.0`) was entirely removed from the version script |
| `symbol_moved_version_node` | potential_breaking | Symbol moved from one version node to another (e.g., `LIBFOO_1.0` → `LIBFOO_2.0`) |
| `soname_bump_recommended` | quality_issues | Breaking changes detected but SONAME was not bumped |
| `soname_bump_unnecessary` | quality_issues | SONAME was bumped but no breaking changes detected |
| `version_script_missing` | quality_issues | Library exports symbols without a version script (common oversight) |

### 4b. Version node graph diffing

In `diff_symbols.py` or a new `diff_versioning.py`:

```python
def detect_version_node_changes(old_elf: ElfMetadata, new_elf: ElfMetadata) -> list[Change]:
    """Compare ELF symbol version definition graphs."""
    # Extract version definition entries (VER_DEF)
    # Build graph: version_node → set of symbols
    # Detect:
    #   - Removed version nodes (all symbols in that node gone)
    #   - Symbols migrated between nodes
    #   - New version nodes added
```

### 4c. SONAME bump recommendation

After all detectors run, add a post-detection check:

```python
def check_soname_bump_policy(changes: list[Change], old_elf: ElfMetadata, new_elf: ElfMetadata) -> list[Change]:
    """Check whether SONAME bump is appropriate given detected changes."""
    has_breaking = any(c.verdict == Verdict.BREAKING for c in changes)
    soname_changed = old_elf.soname != new_elf.soname

    if has_breaking and not soname_changed:
        return [Change(kind=ChangeKind.SONAME_BUMP_RECOMMENDED, ...)]
    if not has_breaking and soname_changed:
        return [Change(kind=ChangeKind.SONAME_BUMP_UNNECESSARY, ...)]
    return []
```

### 4d. Actionable messages

Each new change kind should include guidance in its message:

```text
SONAME_BUMP_RECOMMENDED: 3 binary-incompatible changes detected but SONAME
remains libfoo.so.1. Consumers linked against libfoo.so.1 will encounter
runtime failures. Recommended: bump SONAME to libfoo.so.2.

SYMBOL_MOVED_VERSION_NODE: Symbol foo::bar() moved from version node LIBFOO_1.0
to LIBFOO_2.0. Applications linked against LIBFOO_1.0 will not find this symbol
at the expected version. This is typically intentional during a major release.
```

**Implementation notes:**
- Version definition parsing: `ElfMetadata` already extracts some versioning info.
  Extend to capture the full `VER_DEF` / `VER_NEED` graph structure.
- The SONAME bump check runs as a post-detector (after all other detectors), since
  it needs the full change list to make its recommendation.
- Register new ChangeKinds in `change_registry.py` with appropriate default severities.
- Add to policy profiles: `strict_abi` treats `soname_bump_recommended` as BREAKING;
  `sdk_vendor` treats it as COMPATIBLE_WITH_RISK.

**Tests:**
- Test with library that removes a version node
- Test with symbol migration between nodes
- Test SONAME bump recommendation (breaking changes, no SONAME change)
- Test SONAME bump unnecessary (no breaking changes, SONAME changed)
- Test library with no version script at all
- Parity: check against known Fedora library upgrades that bumped SONAME

---

## 5. Debian Symbols File Adapter

**Extends:** ADR-006 (Package-Level Comparison)
**Complexity:** M (2-3 days)
**Why no ADR:** Export format adapter, no architectural decisions.

### Prompt

Add the ability to generate and validate Debian `symbols` files from abicheck's
analysis. This integrates abicheck with Debian/Ubuntu packaging workflows where
`dpkg-gensymbols` and `dpkg-shlibdeps` use `symbols` files for fine-grained
dependency tracking.

**What to build:**

### 5a. Generate Debian symbols file

New command:

```bash
abicheck debian-symbols libfoo.so -o debian/libfoo1.symbols
```

Output format (Debian symbols file):

```text
libfoo.so.1 libfoo1 #MINVER#
 _ZN3foo3barEv@Base 1.0
 _ZN3foo3bazEi@Base 1.0
 _ZN3foo9new_thingEv@Base 1.1
 (c++)"foo::Config::Config()@Base" 1.0
 (c++)"foo::Config::~Config()@Base" 1.0
```

**Mapping:**
- Library SONAME → first line (library, package name, minimum version)
- Each exported symbol → one line with `@Base` or `@VERSION_NODE` and version
- C++ symbols: demangled form with `(c++)` prefix (Debian convention)
- Version comes from: symbol version nodes if present, else user-specified `--version`

### 5b. Validate existing symbols file against binary

```bash
abicheck debian-symbols --validate libfoo.so --symbols debian/libfoo1.symbols
```

Output:

```text
Symbols validation for libfoo.so.1:
  MISSING from binary (in symbols file but not exported):
    _ZN3foo6legacyEv@Base 1.0

  NEW in binary (exported but not in symbols file):
    _ZN3foo9new_thingEv@Base

  VERSION MISMATCH:
    (none)

Result: FAIL (1 missing symbol)
```

### 5c. Generate symbols diff

```bash
abicheck debian-symbols --diff old/libfoo1.symbols new/libfoo1.symbols
```

**Implementation notes:**
- New file: `abicheck/debian_symbols.py`
- New CLI command group: `abicheck debian-symbols`
- Parse the Debian symbols format (documented in `dpkg-gensymbols(1)`)
- Handle both mangled and demangled forms
- Handle optional tags: `(c++)`, `(symver)`, `(arch=amd64)`, etc.
- Use existing `demangle.py` for C++ symbol demangling
- For `--validate`, exit code 0 = match, exit code 2 = mismatch

**Tests:**
- Generate symbols file from example libraries
- Round-trip: generate → validate against same binary → pass
- Validate against modified binary → detect missing/new symbols
- Handle C++ symbols with template parameters
- Handle versioned symbols

---

## 6. Stripped Binary Heuristics (Exploratory)

**Extends:** ADR-003 (Data Source Architecture)
**Complexity:** L-XL (exploratory, 2-4 weeks)
**Why no ADR needed now:** This is exploratory/research. Write an ADR if the
prototype proves valuable.

### Prompt

Explore lightweight binary similarity techniques that can reduce false "removed +
added" churn when comparing stripped binaries in symbols-only mode. This is NOT
about becoming a reverse engineering tool — it's about improving the quality of
symbol-level diff results.

**What to explore:**

1. **LIEF integration for normalized metadata extraction:**
   - Replace/augment pyelftools+pefile+macholib with LIEF for a unified API
   - Extract: sections, segments, imports, exports, relocations across all formats
   - Benefit: single library instead of three; richer metadata (relocations, CFI)
   - Risk: LIEF is a C++ library with Python bindings — heavier dependency

2. **Function size/hash fingerprinting:**
   - For exported functions with symbols: compute (code_size, instruction_hash)
   - Use as a secondary matching signal when symbol names change (rename detection)
   - Example: `libfoo_v1_create()` → `libfoo_create()` with identical code → likely rename

3. **Section-level change summary:**
   - Compare `.text` size, `.rodata` content hashes, `.data` layout
   - Provide coarse "binary changed significantly" vs "binary barely changed" signal
   - Useful for triaging: if `.text` didn't change, ABI probably didn't either

**What NOT to build (out of scope):**
- Full disassembly or CFG extraction
- BinDiff/Ghidra integration
- Instruction-level analysis
- Anything requiring architecture-specific knowledge

**Output:** A prototype in `abicheck/binary_fingerprint.py` with:
- `compute_function_fingerprints(binary_path) -> dict[str, FunctionFingerprint]`
- `match_renamed_functions(old_fps, new_fps) -> list[RenameCandidate]`
- Integration point: feed `RenameCandidate` results into the diff engine to
  convert "removed + added" pairs into "renamed" changes

If the prototype shows value (measurable reduction in false removed/added pairs),
write an ADR and integrate properly.
