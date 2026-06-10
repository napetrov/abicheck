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

"""Header-scoped source-mode toolchain robustness (plan G16).

Header-scoped scans drive an internal clang frontend (via castxml) while
emulating the host GCC. In the real-world scan campaign these aborted before any
ABI comparison for a small family of host-toolchain parse failures — always the
same three signatures, never an abicheck logic bug:

* glibc sized-float keywords ``_Float32``/``_Float64``/``_Float128`` the bundled
  clang frontend rejects (the dominant case);
* the GCC 13+ libstdc++ ``__assume__`` attribute;
* explicit ``--lang c`` on headers that need C++ or guard ``extern "C"``.

These tests pin (a) the actionable remediation text for each signature and
(b) the one-shot auto-retry with the ``-D_FloatN`` compatibility shim. They are
fully mocked, so they run in the default fast lane with no castxml present.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from abicheck.dumper import (
    _FLOATN_SHIM_DEFINES,
    _build_castxml_command,
    _castxml_failure_hint,
    _stderr_wants_floatn_shim,
)

# A captured-shape stderr for each known signature.
_FLOATN_STDERR = (
    "/usr/include/bits/floatn-common.h:214:14: error: unknown type name '_Float32'"
)
_FLOATN128_STDERR = "error: unknown type name '_Float128x'"
_ASSUME_STDERR = (
    "/usr/include/c++/13/bits/stl_algobase.h:2070: error: '__assume__' was not declared"
)


def _make_completed_process(
    returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess:
    result: subprocess.CompletedProcess = MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = returncode
    result.stderr = stderr
    result.stdout = ""
    return result


class TestFloatNShimTrigger:
    def test_matches_sized_float_keywords(self) -> None:
        assert _stderr_wants_floatn_shim(_FLOATN_STDERR)
        assert _stderr_wants_floatn_shim(_FLOATN128_STDERR)
        assert _stderr_wants_floatn_shim("unknown type name '_Float64'")

    def test_ignores_unrelated_failures(self) -> None:
        assert not _stderr_wants_floatn_shim("fatal error: header.h: No such file")
        assert not _stderr_wants_floatn_shim("")
        # bare word 'Float' without the _FloatN keyword shape must not match
        assert not _stderr_wants_floatn_shim("error: use of undeclared 'FloatThing'")


class TestFailureHint:
    def test_floatn_hint_mentions_auto_retry_first_time(self) -> None:
        hint = _castxml_failure_hint(_FLOATN_STDERR, force_cpp=True, headers=[])
        assert "_Float" in hint
        assert "retry" in hint.lower()

    def test_floatn_hint_escalates_after_shim_failed(self) -> None:
        hint = _castxml_failure_hint(
            _FLOATN_STDERR, force_cpp=True, headers=[], floatn_shim_tried=True
        )
        assert "even after" in hint.lower()
        # points the user at a concrete remediation
        assert "--gcc-path" in hint or "newer castxml" in hint

    def test_assume_attribute_hint(self) -> None:
        hint = _castxml_failure_hint(_ASSUME_STDERR, force_cpp=True, headers=[])
        assert "__assume__" in hint
        assert "libstdc++" in hint

    def test_lang_c_on_cpp_headers_hint(self, tmp_path: Path) -> None:
        header = tmp_path / "api.h"
        header.write_text("namespace ns { class C {}; }\n", encoding="utf-8")
        hint = _castxml_failure_hint(
            "error: expected ';'", force_cpp=False, headers=[header]
        )
        assert "--lang" in hint

    def test_no_hint_for_unknown_failure(self, tmp_path: Path) -> None:
        header = tmp_path / "api.h"
        header.write_text("int f(void);\n", encoding="utf-8")
        hint = _castxml_failure_hint(
            "fatal error: missing.h: No such file", force_cpp=False, headers=[header]
        )
        assert hint == ""


class TestCommandShim:
    def test_extra_defines_appended(self) -> None:
        cmd = _build_castxml_command(
            "g++",
            "gnu",
            [],
            Path("/tmp/out.xml"),
            Path("/tmp/agg.hpp"),
            force_cpp=True,
            extra_defines=_FLOATN_SHIM_DEFINES,
        )
        for d in _FLOATN_SHIM_DEFINES:
            assert d in cmd
        # each shim define is a single argv token, value may contain a space
        assert "-D_Float64x=long double" in cmd

    def test_no_defines_by_default(self) -> None:
        cmd = _build_castxml_command(
            "g++",
            "gnu",
            [],
            Path("/tmp/out.xml"),
            Path("/tmp/agg.hpp"),
            force_cpp=True,
        )
        assert not any(c.startswith("-D_Float") for c in cmd)


_VALID_XML = b'<CastXML><Namespace id="_1" name=""/></CastXML>'


class TestAutoRetry:
    """The one-shot retry: a sized-float failure triggers exactly one re-run
    carrying the shim, and a healthy retry yields a snapshot."""

    def test_retry_with_shim_succeeds(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(list(cmd))
            o_idx = cmd.index("-o")
            out_path = Path(cmd[o_idx + 1])
            if len(calls) == 1:
                # first attempt: sized-float parse failure, no output written
                return _make_completed_process(returncode=1, stderr=_FLOATN_STDERR)
            # retry: shim present → succeeds and writes valid XML
            assert "-D_Float32=float" in cmd
            out_path.write_bytes(_VALID_XML)
            return _make_completed_process(returncode=0)

        with (
            patch("abicheck.dumper._castxml_available", return_value=True),
            patch("abicheck.dumper.subprocess.run", side_effect=fake_run),
            patch("abicheck.dumper._cache_path", return_value=tmp_path / "cache.xml"),
        ):
            from abicheck.dumper import _castxml_dump

            header = tmp_path / "api.hpp"
            header.write_text("int f();\n", encoding="utf-8")
            root = _castxml_dump([header], [])

        assert root is not None
        assert len(calls) == 2  # exactly one retry
        assert not any(c.startswith("-D_Float") for c in calls[0])
        assert "-D_Float32=float" in calls[1]

    def test_retry_failure_raises_escalated_hint(self, tmp_path: Path) -> None:
        def fake_run(cmd, **kwargs):  # noqa: ANN001
            # both attempts fail with the sized-float signature
            return _make_completed_process(returncode=1, stderr=_FLOATN_STDERR)

        with (
            patch("abicheck.dumper._castxml_available", return_value=True),
            patch("abicheck.dumper.subprocess.run", side_effect=fake_run),
            patch("abicheck.dumper._cache_path", return_value=tmp_path / "cache.xml"),
        ):
            from abicheck.dumper import _castxml_dump

            header = tmp_path / "api.hpp"
            header.write_text("int f();\n", encoding="utf-8")
            with pytest.raises(RuntimeError, match="even after"):
                _castxml_dump([header], [])

    def test_no_retry_for_unrelated_failure(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(list(cmd))
            return _make_completed_process(
                returncode=1, stderr="fatal error: missing.h: No such file"
            )

        with (
            patch("abicheck.dumper._castxml_available", return_value=True),
            patch("abicheck.dumper.subprocess.run", side_effect=fake_run),
            patch("abicheck.dumper._cache_path", return_value=tmp_path / "cache.xml"),
        ):
            from abicheck.dumper import _castxml_dump

            header = tmp_path / "api.hpp"
            header.write_text("int f();\n", encoding="utf-8")
            with pytest.raises(RuntimeError, match="castxml failed"):
                _castxml_dump([header], [])

        assert len(calls) == 1  # no retry for non-floatn failures
