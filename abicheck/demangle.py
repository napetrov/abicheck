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

"""Shared C++ name demangling utilities.

Used by dwarf_snapshot.py (FIX-B) and appcompat.py (FIX-A Part 3) for
cross-format symbol matching.
"""

from __future__ import annotations

import functools
import logging
import subprocess

_log = logging.getLogger(__name__)

# Whether we have already warned about demangling being unavailable.
_warned_no_demangler = False


@functools.lru_cache(maxsize=4096)
def demangle(symbol: str) -> str | None:
    """Demangle a single Itanium C++ symbol. Returns *None* if not C++.

    Tries ``cxxfilt`` (Python binding to ``__cxa_demangle``) first, then
    falls back to the ``c++filt`` command-line tool.
    """
    if not symbol or not symbol.startswith("_Z"):
        return None
    try:
        import cxxfilt
        return cxxfilt.demangle(symbol)
    except Exception:  # noqa: BLE001
        pass
    try:
        result = subprocess.run(
            ["c++filt", symbol],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            if out and out != symbol:
                return out
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    global _warned_no_demangler  # noqa: PLW0603
    if not _warned_no_demangler:
        _log.warning(
            "C++ demangling unavailable (no cxxfilt package and no c++filt binary); "
            "DWARF export matching and appcompat symbol matching may be incomplete"
        )
        _warned_no_demangler = True
    return None


def demangle_batch(symbols: list[str]) -> dict[str, str]:
    """Demangle a batch of symbols efficiently using a single ``c++filt`` call.

    Returns a mapping from mangled → demangled for symbols that were
    successfully demangled. Non-C++ symbols are excluded from the result.
    """
    cpp_syms = [s for s in symbols if s and s.startswith("_Z")]
    if not cpp_syms:
        return {}

    # Try cxxfilt first (in-process, fastest)
    try:
        import cxxfilt
        result = {}
        for s in cpp_syms:
            try:
                d = cxxfilt.demangle(s)
                if d and d != s:
                    result[s] = d
            except Exception:  # noqa: BLE001
                pass
        if result:
            return result
    except ImportError:
        pass

    # Fallback: batch c++filt call
    try:
        proc = subprocess.run(
            ["c++filt"],
            input="\n".join(cpp_syms),
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0:
            lines = proc.stdout.strip().split("\n")
            result = {}
            for mangled, demangled in zip(cpp_syms, lines):
                if demangled and demangled != mangled:
                    result[mangled] = demangled
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return {}


def base_name(symbol: str) -> str:
    """Extract the unqualified function name from a symbol (best-effort).

    Known limitations: ``operator<<``, ``operator()``, and templates with
    ``::`` inside angle brackets may be parsed incorrectly. Only used for
    display, not for matching.

    Examples::

        "_ZNK6Widget8getValueEv" → "getValue"
        "Widget::getValue() const" → "getValue"
        "add" → "add"
    """
    demangled = demangle(symbol)
    if demangled:
        paren = demangled.find("(")
        prefix = demangled[:paren] if paren != -1 else demangled
        parts = prefix.rsplit("::", 1)
        return parts[-1].strip()
    return symbol
