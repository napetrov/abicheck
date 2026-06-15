# abicheck Clang plugin (`abicheck-facts`)

> Status: **optional optimization**, reference implementation. Not built or
> gated in CI. The supported portable producer is the `abicheck-cc` compiler
> wrapper (`abicheck/cc_wrapper.py`) and `compile_commands.json` replay
> (`abicheck dump --sources`). See ADR-035 D5.

A Clang plugin that, **during a normal compile**, emits abicheck's normalized
Flow-2 source facts (`source_facts/*.jsonl`) directly from the AST Clang already
built — removing the second front-end pass the `abicheck-cc` wrapper otherwise
runs. The output is the **same `abicheck_inputs/` protocol** abicheck ingests via
`merge`, so the plugin is a drop-in faster producer, never a new format.

## Why it is optional

Clang plugins are compiler-version-sensitive: a plugin built against LLVM N must
match the `clang` that loads it. That is why abicheck does **not** require it —
`compile_commands.json` replay + LibTooling/CastXML is the portable, supported
path (ADR-035 D5, ADR-032 action ceiling). Reach for the plugin only when the
second-frontend cost is measurable on a large build and you control the toolchain
image.

## What it emits

One JSON object per translation unit, appended to
`$ABICHECK_INPUTS_DIR/source_facts/<tu>.jsonl`, matching
`abicheck.buildsource.source_abi.SourceAbiTu` (the canonical schema — see that
module for the field contract). Minimum useful fields per TU:

- `tu_id`, `target_id`, `source`, `public_header_roots`
- `functions` / `types` / `macros` / … — each a `SourceEntity`
  (`id`, `kind`, `qualified_name`, `mangled_name`, `signature_hash`, `value`,
  `source_location {path,line,origin}`, `visibility`, `api_relevant`)

Raw AST dumps (`raw_ast/`) are **forensic only** — abicheck does not ingest them;
the plugin must normalize to `source_facts` itself.

## Build

```bash
cmake -S . -B build -DCMAKE_PREFIX_PATH="$(llvm-config --cmakedir)/.."
cmake --build build
```

## Use

```bash
clang++ -std=c++17 -Iinclude \
  -fplugin=./build/libabicheck-facts.so \
  -fplugin-arg-abicheck-facts-out=abicheck_inputs \
  -c src/foo.cpp -o foo.o

# then, exactly as with the wrapper:
abicheck merge libfoo.bin.json ./abicheck_inputs/ -o libfoo.baseline.json
```

## Compiler fallbacks (documented, not required)

A build that cannot load a Clang plugin can still feed Flow 2:

- **`abicheck-cc` wrapper** — the portable default; wraps any compiler and runs
  the castxml/clang extractor as a companion action. No plugin needed.
- **GCC** — `-fdump-lang-class` / `-fdump-translation-unit` produce class/TU
  dumps; a small normalizer (not shipped) converts them to `source_facts`.
- **MSVC** — no AST plugin ABI; use the `abicheck-cc` wrapper around `cl.exe`, or
  emit `source_facts` from your own tooling.

In every case the *output contract is identical* — the `abicheck_inputs/` pack —
so the ingest (`abicheck merge`) is the same regardless of producer.
