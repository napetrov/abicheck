# CLI Review: Commands, Naming, Logic, and Ease of Use

Reviewed: 2026-03-13

## Overview

abicheck has four CLI commands: `dump`, `compare`, `compat`, and `compat-dump`.
The native commands (`dump`, `compare`) are clean and well-designed. The compat
commands (`compat`, `compat-dump`) faithfully replicate ABICC's interface. This
review identifies issues that may block users or CI pipelines, and suggests
improvements.

---

## High Priority

### 1. Exit code inconsistency between `compare` and `compat`

The same verdict produces different exit codes depending on which command is used:

| Verdict | `compare` exit | `compat` exit |
|---|---|---|
| BREAKING | 4 | 1 |
| API_BREAK | 2 | 2 |
| NO_CHANGE/COMPATIBLE | 0 | 0 |

The `compat` command correctly mirrors ABICC (exit 1 = breaking). The `compare`
command uses exit 4 for BREAKING, which is undocumented and surprising. CI
scripts that check for specific exit codes will behave differently depending on
which command is used, even though both commands perform the same core analysis.

**Location:** `cli.py:361-364`, `compat/cli.py:1236-1239`

**Recommendation:** Document exit codes in `compare --help`. Consider aligning
`compare` to use exit 1 for BREAKING, or clearly document the rationale for
exit 4.

### 2. `-o` flag collision between commands

In `dump` and `compare`, `-o` means `--output` (the report file path).
In `compat`, `-o` is an alias for `-old` (the old descriptor path).

A user switching between `compare` and `compat` will be surprised by `-o`
meaning completely different things. This can cause silent misuse — passing a
descriptor path where an output path is expected, or vice versa.

**Location:** `compat/cli.py:686`

**Recommendation:** Consider dropping `-o` as an alias for `-old` in `compat`.
The alias `-d1` already provides a short form, and ABICC documentation
typically uses `-old` not `-o`. At minimum, note this in `compat --help`.

### 3. Fragile snapshot reconstruction (missing fields)

Multiple locations reconstruct `AbiSnapshot` by listing every field manually
instead of using `dataclasses.replace()`. This is fragile: if a field is added
to `AbiSnapshot`, these copies silently lose it.

The reconstruction at `compat/cli.py:655-666` is already missing fields that
exist at `compat/cli.py:1005-1011`. Both are missing `constants`,
`elf_only_mode`, `platform`, and `language_profile`.

**Location:** `compat/cli.py:655-666`, `compat/cli.py:1005-1011`,
`compat/cli.py:630-631`

**Recommendation:** Replace all manual reconstructions with
`dataclasses.replace(snap, version=new_version)`.

---

## Medium Priority

### 4. `dump` exit code 2 clashes with API_BREAK semantic

The `dump` command uses `sys.exit(2)` for errors (`cli.py:168`), but `compare`
uses exit 2 for API_BREAK. A pipeline that chains `dump` then `compare` could
misinterpret a dump failure as "source-level API break."

**Recommendation:** Use `sys.exit(1)` or `click.ClickException` for dump
errors to avoid semantic collision.

### 5. Inconsistent error handling across commands

- `dump`: manual `click.echo()` + `sys.exit(2)`
- `compare`: `click.ClickException` / `click.UsageError` (exit 1)
- `compat`: custom `_compat_fail()` with exit codes 3-11

Three different error patterns across four commands adds cognitive overhead.

**Recommendation:** Standardize `dump` to use `click.ClickException` like
`compare` does.

### 6. `compare --header` missing `exists=True` validation

In `dump`, headers have `type=click.Path(exists=True, ...)`.
In `compare`, headers have `type=click.Path(path_type=Path)` without
`exists=True`. Validation happens later in `_resolve_input`, but the error
messages differ in format between commands.

**Location:** `cli.py:138` vs `cli.py:182`

**Recommendation:** Add `exists=True` to `-H/--header` in `compare` for
consistent early validation, unless there is a deliberate reason to defer.

### 7. Missing cross-compilation flags in native `dump` command

The `dump()` function accepts `gcc_path`, `gcc_prefix`, `gcc_options`,
`sysroot`, `nostdinc`, and `lang`, but the `dump` CLI command only exposes
`--compiler`. These flags are available in `compat-dump` but not in the native
command.

Users needing cross-compilation are forced to use `compat-dump` with an XML
descriptor even though `dump` is the simpler workflow.

**Location:** `cli.py:136-147` vs `dumper.py:705-718`

**Recommendation:** Expose cross-compilation options in the `dump` command.

---

## Low Priority

### 8. Naming observations

- **`compat-dump`** reads as "dump compatibility" rather than "dump in compat
  mode." Grouping as `abicheck compat dump` would be clearer, though this is a
  breaking change.
- **`--compiler`** in `dump`/`compare` suggests picking a compiler but really
  selects a castxml frontend mode (`c++` or `cc`). A name like `--lang` or
  `--castxml-frontend` would be more precise.
- **`-d1`/`-d2`** aliases in `compat` are ABICC legacy and cryptic. Fine to
  keep for backward compatibility but should not be promoted in examples.

### 9. No `--verbose` / `--debug` flag on native commands

The `compat` command has `-q`/`-quiet` and full logging infrastructure, but
`dump` and `compare` have no verbosity control. Users debugging castxml or
comparison issues have no way to get diagnostic output.

### 10. Emoji in warning message

`cli.py:326` uses a Unicode emoji in a warning message. No other warning does
this. This can cause rendering issues in ASCII-only CI logs.

**Recommendation:** Remove the emoji or replace with a plain text marker.

---

## Summary

| # | Issue | Severity | Type |
|---|---|---|---|
| 1 | Exit code inconsistency (compare=4, compat=1) | High | Logic |
| 2 | `-o` flag collision (output vs old) | High | Naming |
| 3 | Fragile snapshot reconstruction (missing fields) | High | Bug-prone |
| 4 | `dump` exit code 2 clashes with API_BREAK | Medium | Logic |
| 5 | Inconsistent error handling patterns | Medium | Code quality |
| 6 | `compare --header` missing `exists=True` | Medium | Validation |
| 7 | Missing cross-compilation flags in `dump` | Medium | Feature gap |
| 8 | Naming: `compat-dump`, `--compiler` | Low | Naming |
| 9 | No `--verbose`/`--debug` on native commands | Low | UX |
| 10 | Emoji in warning message | Low | Portability |
