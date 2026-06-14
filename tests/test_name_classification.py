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

from __future__ import annotations

import pytest

from abicheck.name_classification import (
    ITANIUM_RTTI_PREFIXES,
    LOCAL_RTTI_PREFIXES,
    RTTI_DATA_PREFIXES,
    has_internal_namespace_component,
    is_local_rtti_symbol,
    is_rtti_symbol,
    symbol_origin,
)


@pytest.mark.parametrize(
    "name",
    ["_ZTV4Base", "_ZTI4Base", "_ZTS4Base", "_ZTT4Base", "_ZTc0_4Base", "_ZTh8_N3FooE"],
)
def test_is_rtti_symbol_true(name: str) -> None:
    assert is_rtti_symbol(name)


@pytest.mark.parametrize("name", ["_ZN3Foo3barEv", "main", "", "_Z3fooi"])
def test_is_rtti_symbol_false(name: str) -> None:
    assert not is_rtti_symbol(name)


@pytest.mark.parametrize("name", ["_ZTIZ4mainEUlvE_", "_ZTSZ3fooEUliE_", "_ZTVZ1gEvE", "_ZTTZ1hEvE"])
def test_local_rtti_detected(name: str) -> None:
    assert is_local_rtti_symbol(name)
    # A function-local RTTI symbol is still a generic RTTI symbol.
    assert is_rtti_symbol(name)


def test_non_local_rtti_not_flagged_local() -> None:
    assert not is_local_rtti_symbol("_ZTI4Base")


@pytest.mark.parametrize(
    "name",
    ["_ZN4daal8internal3FooEv", "_ZN3lib6detail4implE", "_ZN3lib8__detailE", "_ZN3lib5_implE"],
)
def test_internal_namespace_component(name: str) -> None:
    assert has_internal_namespace_component(name)


def test_internal_substring_not_matched_without_length_prefix() -> None:
    # "internal" without the conventional length prefix must not match.
    assert not has_internal_namespace_component("_ZN3lib8internelE")  # typo, no "8internal"
    assert not has_internal_namespace_component("my_internal_helper")


def test_symbol_origin_rtti_beats_internal() -> None:
    # RTTI for an internal type classifies as "rtti" (RTTI checked first).
    assert symbol_origin("_ZTIN4daal8internal3FooE") == "rtti"


def test_symbol_origin_buckets() -> None:
    assert symbol_origin("_ZTV4Base") == "rtti"
    assert symbol_origin("_ZN4daal8internal3FooEv") == "internal"
    assert symbol_origin("_ZN3Foo3barEv") == "public"
    assert symbol_origin("") == "public"


def test_data_prefixes_are_subset_of_generic() -> None:
    # The size-owning data objects are a subset of the generic RTTI artifacts.
    assert set(RTTI_DATA_PREFIXES) <= set(ITANIUM_RTTI_PREFIXES)
    # Local-RTTI prefixes are the generic-data prefixes plus the local marker "Z".
    assert all(p[:-1] in ITANIUM_RTTI_PREFIXES for p in LOCAL_RTTI_PREFIXES)


def test_report_summary_reexport_is_same_callable() -> None:
    from abicheck.report_summary import classify_symbol_origin

    assert classify_symbol_origin is symbol_origin
