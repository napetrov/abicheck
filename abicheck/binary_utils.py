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

"""Shared binary format detection utilities.

Provides a single-file-open format detector for ELF, PE, and Mach-O
binaries, replacing duplicated detection logic in cli.py, appcompat.py,
and mcp_server.py.
"""
from __future__ import annotations

from pathlib import Path

# Mach-O magic bytes — covers all variants:
# 32-bit BE/LE, 64-bit BE/LE, fat archive 32/64
_MACHO_MAGICS: frozenset[bytes] = frozenset({
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",  # 32-bit
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",  # 64-bit
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",  # fat archive 32
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",  # fat archive 64
})


def detect_binary_format(path: str | Path) -> str | None:
    """Detect binary format from file magic bytes.

    Returns ``'elf'``, ``'pe'``, ``'macho'``, or ``None`` for unknown/unreadable.
    Uses a single file open and reads only 4 bytes.
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except (OSError, IOError):
        return None
    if magic[:4] == b"\x7fELF":
        return "elf"
    if magic[:2] == b"MZ":
        return "pe"
    if magic[:4] in _MACHO_MAGICS:
        return "macho"
    return None
