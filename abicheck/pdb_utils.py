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

"""PDB file location utilities for Windows PE binaries.

Extracts the PDB path and GUID from the PE debug directory
(IMAGE_DEBUG_TYPE_CODEVIEW / RSDS signature) using ``pefile``.
"""
from __future__ import annotations

import logging
import struct
from pathlib import Path

import pefile  # type: ignore[import-untyped]

log = logging.getLogger(__name__)

# CodeView signature bytes
_RSDS_SIG = b"RSDS"
_NB10_SIG = b"NB10"

# IMAGE_DEBUG_TYPE_CODEVIEW = 2
_DEBUG_TYPE_CODEVIEW = 2


def locate_pdb(dll_path: Path, *, pdb_path_override: Path | None = None) -> Path | None:
    """Find the PDB file for a PE binary.

    Search order:
    1. Explicit ``pdb_path_override`` (from --pdb-path CLI flag)
    2. PDB path embedded in PE debug directory (RSDS/NB10 CodeView entry)
    3. Same directory as the DLL, with ``.pdb`` extension

    Returns the path if found (and the file exists), otherwise ``None``.
    """
    if pdb_path_override is not None:
        if pdb_path_override.is_file():
            return pdb_path_override
        log.warning("locate_pdb: explicit pdb_path does not exist: %s", pdb_path_override)
        return None

    # Try extracting from PE debug directory
    embedded = _extract_pdb_path_from_pe(dll_path)
    if embedded is not None:
        embedded_path = Path(embedded)
        # Try the embedded path directly
        if embedded_path.is_file():
            return embedded_path
        # Try just the filename in the DLL's directory
        local = dll_path.parent / embedded_path.name
        if local.is_file():
            return local

    # Fallback: same name with .pdb extension
    stem_pdb = dll_path.with_suffix(".pdb")
    if stem_pdb.is_file():
        return stem_pdb

    return None


def _extract_pdb_path_from_pe(dll_path: Path) -> str | None:
    """Extract the PDB path string from a PE binary's debug directory.

    Parses IMAGE_DEBUG_DIRECTORY entries for IMAGE_DEBUG_TYPE_CODEVIEW,
    then reads the RSDS or NB10 CodeView header to get the PDB filename.
    """
    try:
        pe = pefile.PE(str(dll_path), fast_load=True)
    except Exception:  # noqa: BLE001
        return None

    try:
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DEBUG"],
        ])

        if not hasattr(pe, "DIRECTORY_ENTRY_DEBUG"):
            return None

        for dbg in pe.DIRECTORY_ENTRY_DEBUG:
            if dbg.struct.Type != _DEBUG_TYPE_CODEVIEW:
                continue

            data = dbg.entry
            if data is None:
                # Fall back to raw data at PointerToRawData
                offset = dbg.struct.PointerToRawData
                size = dbg.struct.SizeOfData
                if offset and size:
                    raw = pe.get_data(dbg.struct.AddressOfRawData, size)
                    if raw and len(raw) >= 24 and raw[:4] == _RSDS_SIG:
                        # RSDS: 4 (sig) + 16 (GUID) + 4 (age) + filename
                        pdb_name = raw[24:].split(b"\x00", 1)[0]
                        return pdb_name.decode("utf-8", errors="replace")
                continue

            # pefile parses the CodeView data into a named structure
            if hasattr(data, "CvSignature"):
                sig_bytes = struct.pack("<I", data.CvSignature)
                if sig_bytes == _RSDS_SIG:
                    if hasattr(data, "PdbFileName"):
                        fname = data.PdbFileName
                        if isinstance(fname, bytes):
                            return fname.rstrip(b"\x00").decode("utf-8", errors="replace")
                        return str(fname)
                elif sig_bytes == _NB10_SIG:
                    if hasattr(data, "PdbFileName"):
                        fname = data.PdbFileName
                        if isinstance(fname, bytes):
                            return fname.rstrip(b"\x00").decode("utf-8", errors="replace")
                        return str(fname)

        return None

    except Exception as exc:  # noqa: BLE001
        log.debug("_extract_pdb_path_from_pe: %s: %s", dll_path, exc)
        return None
    finally:
        pe.close()
