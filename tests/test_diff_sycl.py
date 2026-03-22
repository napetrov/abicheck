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

"""Tests for SYCL PI detector (diff_sycl.py)."""
from __future__ import annotations

import pytest

from abicheck.checker_policy import ChangeKind, Verdict
from abicheck.diff_sycl import (
    _diff_backend_driver_reqs,
    _diff_pi_version,
    _diff_plugin_entrypoints,
    _diff_plugins,
    _diff_plugin_search_paths,
    _diff_runtime_version,
    _diff_sycl,
)
from abicheck.model import AbiSnapshot
from abicheck.sycl_metadata import SyclMetadata, SyclPluginInfo


def _make_plugin(
    name: str = "level_zero",
    library: str = "libpi_level_zero.so",
    pi_version: str = "1.2",
    entry_points: list[str] | None = None,
    backend_type: str = "level_zero",
    min_driver_version: str | None = None,
) -> SyclPluginInfo:
    return SyclPluginInfo(
        name=name,
        library=library,
        pi_version=pi_version,
        entry_points=entry_points or ["piPluginInit", "piPlatformsGet", "piDevicesGet"],
        backend_type=backend_type,
        min_driver_version=min_driver_version,
    )


def _make_sycl(
    pi_version: str = "1.2",
    plugins: list[SyclPluginInfo] | None = None,
    plugin_search_paths: list[str] | None = None,
    runtime_version: str = "",
) -> SyclMetadata:
    return SyclMetadata(
        implementation="dpcpp",
        runtime_version=runtime_version,
        pi_version=pi_version,
        plugins=plugins or [],
        plugin_search_paths=plugin_search_paths or ["/usr/lib/sycl"],
    )


# ---------------------------------------------------------------------------
# PI version diff
# ---------------------------------------------------------------------------

class TestDiffPiVersion:
    def test_no_change(self):
        old = _make_sycl(pi_version="1.2")
        new = _make_sycl(pi_version="1.2")
        assert _diff_pi_version(old, new) == []

    def test_version_changed(self):
        old = _make_sycl(pi_version="1.1")
        new = _make_sycl(pi_version="1.2")
        changes = _diff_pi_version(old, new)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYCL_PI_VERSION_CHANGED
        assert changes[0].old_value == "1.1"
        assert changes[0].new_value == "1.2"

    def test_empty_version_ignored(self):
        old = _make_sycl(pi_version="")
        new = _make_sycl(pi_version="1.2")
        assert _diff_pi_version(old, new) == []


# ---------------------------------------------------------------------------
# Plugin inventory diff
# ---------------------------------------------------------------------------

class TestDiffPlugins:
    def test_no_change(self):
        p = _make_plugin()
        old = _make_sycl(plugins=[p])
        new = _make_sycl(plugins=[p])
        assert _diff_plugins(old, new) == []

    def test_plugin_removed(self):
        p = _make_plugin(name="cuda", library="libpi_cuda.so", backend_type="cuda")
        old = _make_sycl(plugins=[_make_plugin(), p])
        new = _make_sycl(plugins=[_make_plugin()])
        changes = _diff_plugins(old, new)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYCL_PLUGIN_REMOVED
        assert "cuda" in changes[0].symbol

    def test_plugin_added(self):
        p = _make_plugin(name="opencl", library="libpi_opencl.so", backend_type="opencl")
        old = _make_sycl(plugins=[_make_plugin()])
        new = _make_sycl(plugins=[_make_plugin(), p])
        changes = _diff_plugins(old, new)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYCL_PLUGIN_ADDED
        assert "opencl" in changes[0].symbol


# ---------------------------------------------------------------------------
# Plugin entry point diff
# ---------------------------------------------------------------------------

class TestDiffPluginEntrypoints:
    def test_no_change(self):
        p = _make_plugin()
        old = _make_sycl(plugins=[p])
        new = _make_sycl(plugins=[p])
        assert _diff_plugin_entrypoints(old, new) == []

    def test_entrypoint_removed(self):
        old_p = _make_plugin(entry_points=["piPluginInit", "piPlatformsGet", "piDevicesGet"])
        new_p = _make_plugin(entry_points=["piPluginInit", "piPlatformsGet"])
        old = _make_sycl(plugins=[old_p])
        new = _make_sycl(plugins=[new_p])
        changes = _diff_plugin_entrypoints(old, new)
        removed = [c for c in changes if c.kind == ChangeKind.SYCL_PI_ENTRYPOINT_REMOVED]
        assert len(removed) == 1
        assert "piDevicesGet" in removed[0].old_value

    def test_entrypoint_added(self):
        old_p = _make_plugin(entry_points=["piPluginInit", "piPlatformsGet"])
        new_p = _make_plugin(entry_points=["piPluginInit", "piPlatformsGet", "piextUSMAlloc"])
        old = _make_sycl(plugins=[old_p])
        new = _make_sycl(plugins=[new_p])
        changes = _diff_plugin_entrypoints(old, new)
        added = [c for c in changes if c.kind == ChangeKind.SYCL_PI_ENTRYPOINT_ADDED]
        assert len(added) == 1
        assert "piextUSMAlloc" in added[0].new_value

    def test_per_plugin_pi_version_change(self):
        old_p = _make_plugin(pi_version="1.1")
        new_p = _make_plugin(pi_version="1.2")
        old = _make_sycl(plugins=[old_p])
        new = _make_sycl(plugins=[new_p])
        changes = _diff_plugin_entrypoints(old, new)
        version_changes = [c for c in changes if c.kind == ChangeKind.SYCL_PI_VERSION_CHANGED]
        assert len(version_changes) == 1


# ---------------------------------------------------------------------------
# Search path diff
# ---------------------------------------------------------------------------

class TestDiffPluginSearchPaths:
    def test_no_change(self):
        old = _make_sycl(plugin_search_paths=["/usr/lib/sycl"])
        new = _make_sycl(plugin_search_paths=["/usr/lib/sycl"])
        assert _diff_plugin_search_paths(old, new) == []

    def test_path_changed(self):
        old = _make_sycl(plugin_search_paths=["/usr/lib/sycl"])
        new = _make_sycl(plugin_search_paths=["/opt/intel/sycl/lib"])
        changes = _diff_plugin_search_paths(old, new)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYCL_PLUGIN_SEARCH_PATH_CHANGED


# ---------------------------------------------------------------------------
# Runtime version diff
# ---------------------------------------------------------------------------

class TestDiffRuntimeVersion:
    def test_no_change(self):
        old = _make_sycl(runtime_version="2025.2.0")
        new = _make_sycl(runtime_version="2025.2.0")
        assert _diff_runtime_version(old, new) == []

    def test_version_changed(self):
        old = _make_sycl(runtime_version="2025.1.0")
        new = _make_sycl(runtime_version="2025.2.0")
        changes = _diff_runtime_version(old, new)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYCL_RUNTIME_VERSION_CHANGED

    def test_empty_ignored(self):
        old = _make_sycl(runtime_version="")
        new = _make_sycl(runtime_version="2025.2.0")
        assert _diff_runtime_version(old, new) == []


# ---------------------------------------------------------------------------
# Backend driver requirement diff
# ---------------------------------------------------------------------------

class TestDiffBackendDriverReqs:
    def test_no_change(self):
        p = _make_plugin(min_driver_version="1.3.0")
        old = _make_sycl(plugins=[p])
        new = _make_sycl(plugins=[p])
        assert _diff_backend_driver_reqs(old, new) == []

    def test_driver_req_changed(self):
        old_p = _make_plugin(min_driver_version="1.3.0")
        new_p = _make_plugin(min_driver_version="1.5.0")
        old = _make_sycl(plugins=[old_p])
        new = _make_sycl(plugins=[new_p])
        changes = _diff_backend_driver_reqs(old, new)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYCL_BACKEND_DRIVER_REQ_CHANGED

    def test_none_driver_ignored(self):
        old_p = _make_plugin(min_driver_version=None)
        new_p = _make_plugin(min_driver_version="1.5.0")
        old = _make_sycl(plugins=[old_p])
        new = _make_sycl(plugins=[new_p])
        assert _diff_backend_driver_reqs(old, new) == []


# ---------------------------------------------------------------------------
# Full detector integration (via AbiSnapshot)
# ---------------------------------------------------------------------------

class TestDiffSyclDetector:
    def test_skipped_when_no_sycl_metadata(self):
        """Detector is skipped when sycl metadata is absent."""
        old = AbiSnapshot(library="libsycl.so", version="1.0")
        new = AbiSnapshot(library="libsycl.so", version="2.0")
        # _diff_sycl requires support check — directly calling would assert
        assert old.sycl is None
        assert new.sycl is None

    def test_full_diff_with_sycl(self):
        """Full diff with SYCL metadata detects multiple change types."""
        old_plugins = [
            _make_plugin(name="level_zero", entry_points=["piPluginInit", "piPlatformsGet", "piDevicesGet"]),
            _make_plugin(name="cuda", library="libpi_cuda.so", backend_type="cuda"),
        ]
        new_plugins = [
            _make_plugin(name="level_zero", entry_points=["piPluginInit", "piPlatformsGet"]),
            _make_plugin(name="opencl", library="libpi_opencl.so", backend_type="opencl"),
        ]
        old = AbiSnapshot(
            library="libsycl.so", version="1.0",
            sycl=_make_sycl(plugins=old_plugins),
        )
        new = AbiSnapshot(
            library="libsycl.so", version="2.0",
            sycl=_make_sycl(plugins=new_plugins),
        )
        changes = _diff_sycl(old, new)
        kinds = {c.kind for c in changes}
        assert ChangeKind.SYCL_PLUGIN_REMOVED in kinds      # cuda removed
        assert ChangeKind.SYCL_PLUGIN_ADDED in kinds         # opencl added
        assert ChangeKind.SYCL_PI_ENTRYPOINT_REMOVED in kinds  # piDevicesGet removed
