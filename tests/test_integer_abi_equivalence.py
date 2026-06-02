# Copyright 2026 Nikolay Petrov
# SPDX-License-Identifier: Apache-2.0
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

"""ABI-equivalent integer type changes must not be reported as binary breaks.

On LP64, ``size_t`` is ``unsigned long`` and both ``long`` / ``long long`` are
64-bit, so a name-only change between such spellings is not a binary ABI break.
A real width change (``int`` -> ``size_t``) or a signedness change
(``long`` -> ``unsigned long``) must still be reported.
"""

from __future__ import annotations

import pytest

from abicheck.checker import ChangeKind, Verdict, compare
from abicheck.diff_symbols import _abi_equivalent_scalar
from abicheck.model import AbiSnapshot, Function, Param, Visibility


@pytest.mark.parametrize("a,b", [
    ("long", "long long"),
    ("long int", "long long int"),
    ("unsigned long", "size_t"),
    ("long unsigned int", "size_t"),
    ("unsigned long", "uint64_t"),
    ("long", "int64_t"),
    ("int", "int32_t"),
    ("unsigned int", "uint32_t"),
])
def test_lp64_equivalent(a: str, b: str) -> None:
    assert _abi_equivalent_scalar(a, b, is_llp64=False)


@pytest.mark.parametrize("a,b", [
    ("int", "long"),                  # 32 vs 64
    ("int", "size_t"),                # 32 vs 64
    ("long", "unsigned long"),        # signedness differs
    ("size_t", "ssize_t"),            # signedness differs
    ("long*", "long long*"),          # pointers are not bare scalars
    ("int", "float"),                 # float not modelled
])
def test_lp64_not_equivalent(a: str, b: str) -> None:
    assert not _abi_equivalent_scalar(a, b, is_llp64=False)


def test_llp64_long_vs_long_long_differs() -> None:
    # On Windows LLP64 long is 32-bit, so long != long long there.
    assert not _abi_equivalent_scalar("long", "long long", is_llp64=True)
    # size_t stays pointer-width (64) on LLP64, unsigned long is 32 → differ.
    assert not _abi_equivalent_scalar("unsigned long", "size_t", is_llp64=True)


def _fn(ret: str) -> Function:
    return Function(name="f", mangled="f", return_type=ret,
                    params=[], visibility=Visibility.PUBLIC)


def _snap(ver: str, ret: str) -> AbiSnapshot:
    return AbiSnapshot(library="lib.so", version=ver, platform="elf",
                       functions=[_fn(ret)])


def test_return_long_to_long_long_compatible() -> None:
    r = compare(_snap("1", "long"), _snap("2", "long long"))
    assert ChangeKind.FUNC_RETURN_CHANGED not in {c.kind for c in r.changes}
    assert r.verdict in (Verdict.NO_CHANGE, Verdict.COMPATIBLE)


def test_return_int_to_size_t_still_breaking() -> None:
    # 32 -> 64 bit is a real representation change.
    r = compare(_snap("1", "int"), _snap("2", "size_t"))
    assert ChangeKind.FUNC_RETURN_CHANGED in {c.kind for c in r.changes}


def _fn_param(ptype: str) -> Function:
    return Function(name="g", mangled="g", return_type="void",
                    params=[Param(name="a", type=ptype)], visibility=Visibility.PUBLIC)


def test_param_size_t_to_unsigned_long_compatible() -> None:
    old = AbiSnapshot(library="l", version="1", platform="elf", functions=[_fn_param("size_t")])
    new = AbiSnapshot(library="l", version="2", platform="elf", functions=[_fn_param("unsigned long")])
    r = compare(old, new)
    assert ChangeKind.FUNC_PARAMS_CHANGED not in {c.kind for c in r.changes}


def test_param_int_to_long_still_breaking() -> None:
    old = AbiSnapshot(library="l", version="1", platform="elf", functions=[_fn_param("int")])
    new = AbiSnapshot(library="l", version="2", platform="elf", functions=[_fn_param("long")])
    r = compare(old, new)
    assert ChangeKind.FUNC_PARAMS_CHANGED in {c.kind for c in r.changes}
