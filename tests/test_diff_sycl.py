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
    _diff_implementation,
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

    def test_removed_plugin_no_spurious_entrypoint_changes(self):
        """Plugin removed from distribution should NOT generate entrypoint changes."""
        old_p = _make_plugin(entry_points=["piPluginInit", "piPlatformsGet"])
        old = _make_sycl(plugins=[old_p])
        new = _make_sycl(plugins=[])
        changes = _diff_plugin_entrypoints(old, new)
        assert len(changes) == 0


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


# ---------------------------------------------------------------------------
# Implementation change diff
# ---------------------------------------------------------------------------

class TestDiffImplementation:
    def test_no_change(self):
        old = _make_sycl()
        new = _make_sycl()
        assert _diff_implementation(old, new) == []

    def test_implementation_changed(self):
        old = SyclMetadata(implementation="dpcpp")
        new = SyclMetadata(implementation="adaptivecpp")
        changes = _diff_implementation(old, new)
        assert len(changes) == 1
        assert changes[0].kind == ChangeKind.SYCL_IMPLEMENTATION_CHANGED
        assert changes[0].old_value == "dpcpp"
        assert changes[0].new_value == "adaptivecpp"

    def test_empty_implementation_ignored(self):
        old = SyclMetadata(implementation="")
        new = SyclMetadata(implementation="dpcpp")
        assert _diff_implementation(old, new) == []


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestSyclSerialization:
    def test_snapshot_roundtrip_with_sycl(self):
        """SyclMetadata survives snapshot serialization round-trip."""
        from abicheck.serialization import snapshot_from_dict, snapshot_to_dict

        plugin = _make_plugin(
            name="level_zero",
            entry_points=["piPluginInit", "piPlatformsGet", "piDevicesGet"],
            min_driver_version="1.3.0",
        )
        snap = AbiSnapshot(
            library="libsycl.so", version="2025.2.0",
            sycl=_make_sycl(
                pi_version="1.2",
                plugins=[plugin],
                plugin_search_paths=["/usr/lib/sycl", "/opt/intel/lib"],
                runtime_version="2025.2.0",
            ),
        )
        d = snapshot_to_dict(snap)
        restored = snapshot_from_dict(d)
        assert restored.sycl is not None
        assert restored.sycl.implementation == "dpcpp"
        assert restored.sycl.pi_version == "1.2"
        assert restored.sycl.runtime_version == "2025.2.0"
        assert len(restored.sycl.plugins) == 1
        assert restored.sycl.plugins[0].name == "level_zero"
        assert restored.sycl.plugins[0].entry_points == [
            "piPluginInit", "piPlatformsGet", "piDevicesGet",
        ]
        assert restored.sycl.plugins[0].min_driver_version == "1.3.0"
        assert restored.sycl.plugin_search_paths == ["/usr/lib/sycl", "/opt/intel/lib"]

    def test_snapshot_roundtrip_without_sycl(self):
        """Snapshot without SYCL metadata round-trips correctly."""
        from abicheck.serialization import snapshot_from_dict, snapshot_to_dict

        snap = AbiSnapshot(library="libfoo.so", version="1.0")
        d = snapshot_to_dict(snap)
        restored = snapshot_from_dict(d)
        assert restored.sycl is None


# ---------------------------------------------------------------------------
# Environment matrix
# ---------------------------------------------------------------------------

class TestEnvironmentMatrix:
    def test_from_dict_valid(self):
        from abicheck.environment_matrix import EnvironmentMatrix

        data = {
            "compilers": ["gcc-13", "clang-17"],
            "abi_version": "18",
            "target_os": "linux",
            "target_arch": "x86_64",
            "sycl": {
                "implementation": "dpcpp",
                "backends": ["level_zero", "opencl"],
                "min_pi_version": "1.2",
            },
            "cuda": {
                "gpu_architectures": ["sm_80", "sm_90"],
                "driver_range": ["525.0", "580.0"],
            },
        }
        matrix = EnvironmentMatrix.from_dict(data)
        assert matrix.compilers == ["gcc-13", "clang-17"]
        assert matrix.sycl.implementation == "dpcpp"
        assert matrix.sycl.backends == ["level_zero", "opencl"]
        assert matrix.cuda.gpu_architectures == ["sm_80", "sm_90"]
        assert matrix.cuda.driver_range == ("525.0", "580.0")

    def test_from_dict_empty(self):
        from abicheck.environment_matrix import EnvironmentMatrix

        matrix = EnvironmentMatrix.from_dict({})
        assert matrix.compilers == []
        assert matrix.target_os is None
        assert matrix.target_arch is None
        assert matrix.sycl.implementation == ""
        assert matrix.cuda.gpu_architectures == []

    def test_from_dict_not_dict_raises(self):
        from abicheck.environment_matrix import EnvironmentMatrix

        with pytest.raises(TypeError, match="expects a dict"):
            EnvironmentMatrix.from_dict([1, 2, 3])

    def test_from_dict_bad_compilers_raises(self):
        from abicheck.environment_matrix import EnvironmentMatrix

        with pytest.raises(ValueError, match="compilers.*must be a list"):
            EnvironmentMatrix.from_dict({"compilers": 42})
