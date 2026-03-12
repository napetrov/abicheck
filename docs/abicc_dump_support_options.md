# Supporting ABICC `ABI.dump` files as input

## Short answer

Yes — supporting existing `ABI.dump` inputs is practical.

The key question is **scope**:

- **Practical and relatively fast:** support classic Perl `Data::Dumper` dumps well enough for compatibility verdicts (MVP).
- **More expensive:** full-fidelity parity across all ABICC dump variants and corner cases.

## Current state

`abicheck compat` currently accepts:

- ABICC XML descriptors (via `parse_descriptor(...)`),
- native `abicheck` JSON snapshots (via `load_snapshot(...)`), and
- minimal ABICC Perl `Data::Dumper` dumps (`.dump`, `$VAR1 = { ... }`).

It still rejects ABICC XML dump variants (`<ABI_dump...>` / `<abi_dump...>`).

This behavior is implemented in `_load_descriptor_or_dump(...)` in `abicheck/cli.py`.

## Why your migration attempt fails

Your secp256k1 flow generates classic `abi-dumper` artifacts (`ABI.dump`) and then feeds those files directly to compatibility checking.

That is exactly the input shape `abi-compliance-checker` expects; with minimal Perl-dump support, this migration path is now directly addressable in `compat`.

## What an ABICC dump contains (practical parsing anchor)

`abi-dumper` writes a top-level Perl hash (via `Data::Dumper`) with stable core keys such as:

- `LibraryName`, `LibraryVersion`, `Language`, `Arch`, `WordSize`
- `SymbolInfo`, `Symbols`, `UndefinedSymbols`, `SymbolVersion`
- `TypeInfo`, `Headers`, `Sources`, `Needed`

This is defined in `createABIFile()` in upstream `abi-dumper`.

Implication: the format is **structured enough** for conversion to `AbiSnapshot`, even if some niche fields are ignored initially.

## Feasibility and effort (realistic)

### Complexity by target

| Target | What you support | Estimated effort |
|---|---|---|
| **MVP** | Perl `.dump` importer for core symbols/types needed by `compat` verdicts | **~1–2 weeks** |
| **Robust** | Better type coverage + templates + symbol version edge cases + fixture corpus | **~3–5 weeks** |
| **Near-parity** | Perl + ABICC XML dump, broad corpus parity checks, strict/lenient modes | **~6–10 weeks** |

### Risk by parsing strategy

1. **Pure Python parser for Perl dumps**
   - Highest long-term control, but more implementation effort (Perl grammar quirks).
2. **Perl bridge converter (recommended first)**
   - Use Perl to deserialize dump, emit JSON; Python maps JSON -> `AbiSnapshot`.
   - Fastest path because it avoids reimplementing Perl syntax parsing.
3. **Delegate fully to legacy ABICC tooling**
   - Fast prototype, but keeps heavy external dependency footprint.

## Options to add support

### Option A — Native ABICC dump importer inside `compat` (recommended end-state)

Add conversion directly in `_load_descriptor_or_dump(...)`:

- detect ABICC dump input,
- parse dump (Perl and/or ABICC-XML schema),
- convert to `AbiSnapshot`,
- continue through current compare/report pipeline.

**Pros**
- True drop-in CLI parity (`-old ABI.dump -new ABI.dump`).
- No extra user steps.

**Cons**
- Parser scope is non-trivial if aiming for full fidelity immediately.

### Option B — Sidecar converter command (`compat-import`) (recommended first phase)

```bash
abicheck compat-import -in old.ABI.dump -out old.json
abicheck compat-import -in new.ABI.dump -out new.json
abicheck compat -lib foo -old old.json -new new.json
```

**Pros**
- Lower risk, easier iteration, straightforward validation.
- Lets teams unblock now while importer matures.

**Cons**
- Not single-command drop-in yet.

### Option C — Delegate conversion to legacy ABICC tooling

Use ABICC stack to transform dumps into an ingestible intermediate artifact.

**Pros**
- Quick bootstrap.

**Cons**
- Adds Perl/legacy dependency burden and CI fragility.

### Option D — Keep current stance; improve migration docs only

**Pros**
- Minimal engineering effort.

**Cons**
- Does not solve existing dump-based pipelines.

## Recommended implementation plan

1. **Phase 1 (unblock users):** implement `compat-import` for Perl `.dump` with lenient mapping.
2. **Phase 2:** enable `compat` to auto-import `.dump` transparently.
3. **Phase 3:** add ABICC XML dump parsing and broaden fixture parity checks.
4. **Phase 4:** strict/lenient modes + diagnostics for unsupported fields.

## Acceptance criteria for "practical support"

- `abicheck compat -lib X -old old.ABI.dump -new new.ABI.dump` works (possibly via internal conversion).
- Existing exit code semantics remain unchanged.
- For benchmark fixtures, verdict parity vs ABICC is tracked and documented.
- Unsupported fields produce warnings, not hard failures, in lenient mode.

## Practical recommendation for your secp256k1 case

The fastest credible path is:

- ship a **Perl dump importer first** (lenient, verdict-focused),
- cover the secp256k1 flow as a regression fixture,
- then grow toward fuller parity.

This gives immediate value for existing ABICC dump archives without blocking on complete schema parity.
