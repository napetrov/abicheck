# NOTICE — Third-Party Software

This project (`abicheck`) is licensed under the **Apache License 2.0**.

---

## What this project is NOT derived from

| Tool | License | Status |
|------|---------|--------|
| `abi-compliance-checker` (lvc/abi-compliance-checker) | LGPL-2.1 | ❌ No code or tests copied |
| `libabigail` (abidiff/abidw) | LGPL-2.1+ | ❌ No code copied |
| `abi-dumper` (lvc/abi-dumper) | LGPL-2.1 | ❌ No code copied |

All code in this repository was written independently.  
Test fixtures in `tests/fixtures/` are original C/C++ snippets authored for this project.

---

## Runtime / tool dependencies (not linked, invoked as subprocesses)

| Tool | License | Usage |
|------|---------|-------|
| [castxml](https://github.com/CastXML/CastXML) | Apache-2.0 | C++ header → XML dump (subprocess) |
| GCC / Clang | GPL-3.0 / Apache-2.0 | C++ compiler backend for castxml (system tool) |

These tools are invoked as external processes and are **not** distributed with this project.

---

## Python dependencies

| Package | License | Usage |
|---------|---------|-------|
| `click` | BSD-3-Clause | CLI framework |
| `pyyaml` | MIT | YAML parsing (policy files, suppressions) |
| `defusedxml` | PSF-2.0 | Safe XML parsing (ABICC descriptor mode) |
| `pyelftools` | Public Domain | ELF/DWARF binary metadata extraction |
| `google-re2` | BSD-3-Clause | RE2 suppression engine (O(N) guaranteed) |
| `packaging` | Apache-2.0 / BSD-2-Clause | Version comparison for suppressions |

See `pyproject.toml` for the full dependency list.
