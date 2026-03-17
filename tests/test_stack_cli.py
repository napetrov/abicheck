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

"""Tests for CLI commands: abicheck deps / abicheck stack-check."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from abicheck.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def real_binary():
    candidates = [Path("/usr/bin/python3"), Path("/usr/bin/ls"), Path("/bin/ls")]
    for p in candidates:
        if p.exists():
            return p
    pytest.skip("No suitable ELF binary found")


class TestDepsCommand:
    def test_deps_markdown(self, runner, real_binary):
        result = runner.invoke(main, ["deps", str(real_binary)])
        assert result.exit_code == 0
        assert "Stack Report" in result.output
        assert "Dependency Tree" in result.output
        assert "Symbol Binding Summary" in result.output

    def test_deps_json(self, runner, real_binary):
        result = runner.invoke(main, ["deps", str(real_binary), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "root_binary" in data
        assert "verdict" in data
        assert data["verdict"]["loadability"] == "pass"

    def test_deps_output_file(self, runner, real_binary, tmp_path):
        outfile = tmp_path / "deps.json"
        result = runner.invoke(main, [
            "deps", str(real_binary), "--format", "json", "-o", str(outfile),
        ])
        assert result.exit_code == 0
        assert outfile.exists()
        data = json.loads(outfile.read_text())
        assert "root_binary" in data

    def test_deps_nonexistent_binary(self, runner, tmp_path):
        result = runner.invoke(main, ["deps", str(tmp_path / "nonexistent")])
        assert result.exit_code != 0  # Click raises error for non-existent path

    def test_deps_contains_libc(self, runner, real_binary):
        result = runner.invoke(main, ["deps", str(real_binary), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        sonames = [n["soname"] for n in data["baseline_graph"]["nodes"]]
        assert "libc.so.6" in sonames

    def test_deps_binding_summary(self, runner, real_binary):
        result = runner.invoke(main, ["deps", str(real_binary), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "bindings_summary" in data
        assert "resolved_ok" in data["bindings_summary"]
        assert data["bindings_summary"]["resolved_ok"] > 0


class TestStackCheckCommand:
    def test_stack_check_help(self, runner):
        result = runner.invoke(main, ["stack-check", "--help"])
        assert result.exit_code == 0
        assert "baseline" in result.output.lower()
        assert "candidate" in result.output.lower()
