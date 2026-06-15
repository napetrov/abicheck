# Copyright 2026 Nikolay Petrov
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Flow-2 producer side: write/append a normalized ``abicheck_inputs/`` pack.

The inverse of :mod:`inputs_pack` (which *ingests*): these helpers let a build
(the ``abicheck-cc`` wrapper, a Clang plugin, or any tooling that can produce a
:class:`SourceAbiTu`) **emit** a conformant Flow-2 pack — manifest +
``source_facts/*.jsonl`` — that ``abicheck merge`` later ingests with no second
frontend (ADR-035 D5, G19.4).

Two usage shapes:

- **Incremental** (a per-TU compiler wrapper): :func:`init_inputs_pack` once,
  then :func:`append_source_facts` per compiled translation unit.
- **One-shot** (a batch producer or a test fixture): :func:`write_inputs_pack`
  writes the manifest, all facts, and an optional compile DB in one call.

Pure I/O — never runs a compiler. A pack written here round-trips through
:func:`inputs_pack.ingest_inputs_pack`.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from collections.abc import Iterable
from pathlib import Path

from .inputs_pack import (
    DEFAULT_COMPILE_DB_REL,
    INPUTS_MANIFEST_NAME,
    SOURCE_FACTS_DIR,
    InputsManifest,
)
from .source_abi import SourceAbiTu

#: Default JSONL file the incremental writer appends to when no per-TU name is
#: given. A per-TU name (see :func:`facts_filename`) keeps parallel wrapper
#: invocations from racing on one file.
DEFAULT_FACTS_FILE = "facts.jsonl"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _write_manifest(root: Path, manifest: InputsManifest) -> None:
    (root / INPUTS_MANIFEST_NAME).write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def facts_filename(source: str) -> str:
    """Deterministic, collision-resistant ``source_facts`` filename for a TU.

    ``<stem>.<short-hash>.jsonl`` — the stem keeps it human-readable, the hash of
    the full source path keeps two same-named TUs in different directories from
    colliding (and lets parallel wrapper invocations each own a file).
    """
    import hashlib

    stem = Path(source).name or "tu"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    return f"{stem}.{digest}.jsonl"


def init_inputs_pack(
    root: Path | str,
    *,
    library: str = "",
    version: str = "",
    created_by: str = "",
) -> InputsManifest:
    """Create the pack directory + manifest if absent; return the manifest.

    Idempotent: if a manifest already exists it is loaded and returned unchanged,
    so repeated per-TU wrapper invocations share one pack without clobbering it.
    """
    root = Path(root)
    (root / SOURCE_FACTS_DIR).mkdir(parents=True, exist_ok=True)
    mpath = root / INPUTS_MANIFEST_NAME
    if mpath.is_file():
        return InputsManifest.from_dict(json.loads(mpath.read_text(encoding="utf-8")))
    manifest = InputsManifest(
        library=library, version=version, created_by=created_by, created_at=_now()
    )
    _write_manifest(root, manifest)
    return manifest


def append_source_facts(
    root: Path | str,
    tus: Iterable[SourceAbiTu],
    *,
    filename: str = DEFAULT_FACTS_FILE,
) -> Path:
    """Append per-TU dumps as JSON-Lines to ``source_facts/<filename>``.

    One compact, key-sorted JSON object per line (the canonical Flow-2 form).
    Returns the file written. The caller is responsible for having created the
    manifest (see :func:`init_inputs_pack`)."""
    root = Path(root)
    facts_dir = root / SOURCE_FACTS_DIR
    facts_dir.mkdir(parents=True, exist_ok=True)
    path = facts_dir / filename
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        for tu in tus:
            fh.write(json.dumps(tu.to_dict(), sort_keys=True) + "\n")
    return path


def write_inputs_pack(
    root: Path | str,
    *,
    library: str = "",
    version: str = "",
    tus: Iterable[SourceAbiTu] = (),
    created_by: str = "",
    compile_db: Path | str | None = None,
    exported_symbols: Iterable[str] = (),
    binary: str = "",
    headers: Iterable[str] = (),
) -> Path:
    """Write a complete Flow-2 pack in one call; return the pack root.

    Materializes ``manifest.json`` + ``source_facts/facts.jsonl`` and, when
    *compile_db* is given, copies it to ``build/compile_commands.json`` and
    records it in the manifest. Round-trips through ``ingest_inputs_pack``.
    """
    root = Path(root)
    (root / SOURCE_FACTS_DIR).mkdir(parents=True, exist_ok=True)
    manifest = InputsManifest(
        library=library,
        version=version,
        created_by=created_by,
        created_at=_now(),
        exported_symbols=sorted(set(exported_symbols)),
        binary=binary,
        headers=list(headers),
    )
    append_source_facts(root, tus, filename=DEFAULT_FACTS_FILE)
    if compile_db is not None:
        dst = root / DEFAULT_COMPILE_DB_REL
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(compile_db, dst)
        manifest.compile_db = DEFAULT_COMPILE_DB_REL
    _write_manifest(root, manifest)
    return root
