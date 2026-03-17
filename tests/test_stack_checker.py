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

"""Tests for abicheck.stack_checker — full-stack ABI checking."""
from __future__ import annotations

from pathlib import Path

import pytest

from abicheck.stack_checker import StackVerdict, check_single_env


class TestCheckSingleEnv:
    @pytest.fixture
    def real_binary(self):
        candidates = [Path("/usr/bin/python3"), Path("/usr/bin/ls"), Path("/bin/ls")]
        for p in candidates:
            if p.exists():
                return p
        pytest.skip("No suitable ELF binary found")

    def test_loadability_pass(self, real_binary):
        result = check_single_env(real_binary)
        assert result.loadability == StackVerdict.PASS

    def test_abi_risk_pass(self, real_binary):
        result = check_single_env(real_binary)
        assert result.abi_risk == StackVerdict.PASS

    def test_risk_score_low(self, real_binary):
        result = check_single_env(real_binary)
        assert result.risk_score == "low"

    def test_no_missing_symbols(self, real_binary):
        result = check_single_env(real_binary)
        assert len(result.missing_symbols) == 0

    def test_graph_populated(self, real_binary):
        result = check_single_env(real_binary)
        assert result.baseline_graph.node_count >= 2  # At least root + libc

    def test_bindings_populated(self, real_binary):
        result = check_single_env(real_binary)
        assert len(result.bindings_baseline) > 0

    def test_nonexistent_binary(self, tmp_path):
        result = check_single_env(tmp_path / "nonexistent")
        # Empty graph → no missing symbols but also no bindings.
        assert result.baseline_graph.node_count == 0


class TestStackVerdict:
    def test_verdict_values(self):
        assert StackVerdict.PASS.value == "pass"
        assert StackVerdict.WARN.value == "warn"
        assert StackVerdict.FAIL.value == "fail"
