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

"""Make adapter (ADR-029 D7).

Make is too flexible to parse semantically with confidence, so it is supported
as a *reduced-confidence* fallback tier:

1. The preferred Make input is an existing ``compile_commands.json`` (produced
   by Bear / compiledb / intercept-build) — fed through
   :class:`CompileDbAdapter` with ``--build-system make``; this module is not
   needed for that path.
2. This adapter is the next tier: it scrapes a ``make -n`` / ``make --trace``
   *dry-run* transcript for compiler invocations. The dry run does not build
   anything, so it is safe by default (ADR-028 D6); a live ``make -n`` is run
   only when a build directory is given and querying is allowed.

The recovered compile units are always **reduced confidence** (a Make dry run
is not an authoritative target graph), recorded via a diagnostic. Compiler
wrapper / interception (Bear-style) that changes the build invocation is an
explicit opt-in (ADR-032 D5) and is *not* implemented here.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ...build_context import _extract_flags
from ..build_evidence import BuildEvidence, CompileUnit, Generator
from ..redaction import DEFAULT_REDACTION, RedactionPolicy
from .base import (
    compile_unit_id,
    derive_build_options,
    detect_language,
    extract_abi_relevant_flags,
)


class MakeAdapter:
    """Scrape a ``make -n``/``--trace`` transcript into reduced-confidence units."""

    name = "make"

    def __init__(
        self,
        build_dir: Path | str | None = None,
        *,
        dry_run: str | Path | None = None,
        allow_query: bool = True,
        redaction: RedactionPolicy | None = None,
    ) -> None:
        self.build_dir = Path(build_dir) if build_dir is not None else None
        self._dry_run = dry_run
        self.allow_query = allow_query
        self.redaction = redaction or DEFAULT_REDACTION

    def collect(self) -> BuildEvidence:
        ev = BuildEvidence()
        ev.generators.append(Generator(kind="make"))

        text = self._resolve(ev)
        if text is None:
            return ev

        directory = self.build_dir or Path(".")
        for line in text.splitlines():
            cu = self._compile_unit(line, directory)
            if cu is not None:
                ev.compile_units.append(cu)

        if ev.compile_units:
            ev.build_options = derive_build_options(ev.compile_units)
            ev.diagnostics.append(
                f"make: {len(ev.compile_units)} compile units derived from a make "
                "dry-run transcript — reduced confidence (not an authoritative "
                "target graph); prefer a generated compile_commands.json"
            )
        return ev

    # -- input resolution ---------------------------------------------------

    def _resolve(self, ev: BuildEvidence) -> str | None:
        text = _as_text(self._dry_run)
        if text is not None:
            return text
        if self._dry_run is not None:
            ev.diagnostics.append(
                f"make: dry-run input not found or unreadable: "
                f"{self.redaction.path(str(self._dry_run))}"
            )
            return None
        if self.build_dir is not None and self.allow_query:
            return self._run_make_dry_run(ev)
        ev.diagnostics.append("make: no dry-run transcript provided and live query disabled")
        return None

    def _run_make_dry_run(self, ev: BuildEvidence) -> str | None:
        make = shutil.which("make")
        if make is None or self.build_dir is None:
            ev.diagnostics.append("make: executable not found on PATH; cannot run dry-run")
            return None
        # `make -n` only prints the recipes it *would* run; it builds nothing,
        # so this is a query of an existing tree (ADR-028 D6), not a build.
        cmd = [make, "-n", "--print-directory", "-C", str(self.build_dir)]
        try:
            proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                cmd, capture_output=True, text=True, timeout=120, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            ev.diagnostics.append(f"make: dry-run failed: {exc}")
            return None
        if proc.returncode != 0:
            ev.diagnostics.append(
                f"make: dry-run exited {proc.returncode}: {proc.stderr.strip()[:200]}"
            )
            return None
        return proc.stdout

    # -- normalization ------------------------------------------------------

    def _compile_unit(self, line: str, directory: Path) -> CompileUnit | None:
        argv = _split_recipe(line)
        # A translation-unit compile is a `-c` invocation that names a source;
        # link/info/`Entering directory` lines lack one of those and are skipped.
        if "-c" not in argv:
            return None
        source = _source_from_argv(argv)
        if not source:
            return None
        ctx = _extract_flags(argv, directory)
        red_argv = self.redaction.argv(argv)
        red_source = self.redaction.path(source)
        return CompileUnit(
            id=compile_unit_id(red_source, red_argv),
            source=red_source,
            directory=self.redaction.path(str(directory)),
            argv=red_argv,
            language=detect_language(source),
            standard=ctx.language_standard or "",
            defines={k: self.redaction.define_value(k, v or "") for k, v in ctx.defines.items()},
            undefines=sorted(ctx.undefines),
            include_paths=[self.redaction.path(str(p)) for p in ctx.include_paths],
            system_include_paths=[self.redaction.path(str(p)) for p in ctx.system_includes],
            sysroot=self.redaction.path(str(ctx.sysroot)) if ctx.sysroot else None,
            target_triple=ctx.target_triple or "",
            abi_relevant_flags=[self.redaction.arg(f) for f in extract_abi_relevant_flags(argv)],
        )


def _split_recipe(line: str) -> list[str]:
    """Tokenize one make recipe line, tolerating the usual ``@``/trace noise."""
    stripped = line.strip().lstrip("@")  # make silences recipes with a leading @
    if not stripped:
        return []
    try:
        return shlex.split(stripped, posix=os.name != "nt")
    except ValueError:
        return []  # unbalanced quotes / non-command line — skip


def _source_from_argv(argv: list[str]) -> str:
    """Return the first argv token that names a compilable source file."""
    for arg in argv:
        if not arg.startswith(("-", "/")) and detect_language(arg):
            return arg
    return ""


def _as_text(value: str | Path | None) -> str | None:
    """Return text content for a value that may be inline text or a file path."""
    if value is None:
        return None
    candidate = value if isinstance(value, Path) else Path(value)
    try:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return None if isinstance(value, Path) else value
