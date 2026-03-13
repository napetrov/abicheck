# CLI Review: Commands, Naming, Logic, and Ease of Use

Reviewed: 2026-03-13
Status: All issues addressed (see changes below).

## Changes Applied

1. **Exit codes documented** in `compare --help` docstring
2. **`-o` alias removed** from `compat check` (`-old` shorthand is now `-d1` only)
3. **Snapshot reconstruction** fixed with `dataclasses.replace()` (was missing fields)
4. **`dump` error handling** switched to `click.ClickException` (was `sys.exit(2)`)
5. **`compare --header`** now validates `exists=True` at Click level
6. **Cross-compilation flags** exposed in native `dump` command
7. **`compat-dump`** restructured as nested `compat dump` subcommand
8. **`--compiler`** renamed to `--lang` with `click.Choice(["c++", "c"])`
9. **`--verbose`** flag added to `dump` and `compare` commands
10. **Emoji removed** from suppression warning message
