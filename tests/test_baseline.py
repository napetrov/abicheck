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

"""Tests for baseline.py — baseline registry (ADR-022)."""

from __future__ import annotations

from pathlib import Path

import pytest

from abicheck.baseline import (
    BaselineKey,
    BaselineMetadata,
    FilesystemRegistry,
)
from abicheck.model import AbiSnapshot, Function, Visibility


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_snapshot() -> AbiSnapshot:
    """Create a minimal ABI snapshot for testing."""
    return AbiSnapshot(
        library="libfoo.so",
        version="1.0.0",
        functions=[
            Function(
                name="foo",
                mangled="foo",
                return_type="void",
                visibility=Visibility.PUBLIC,
            ),
        ],
    )


@pytest.fixture()
def registry(tmp_path: Path) -> FilesystemRegistry:
    """Create a filesystem registry in a temporary directory."""
    return FilesystemRegistry(tmp_path / "baselines")


# ---------------------------------------------------------------------------
# Tests: BaselineKey
# ---------------------------------------------------------------------------


def test_baseline_key_path() -> None:
    """BaselineKey.path produces correct registry path."""
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    assert key.path == "libfoo/1.0.0/linux-x86_64"


def test_baseline_key_path_with_variant() -> None:
    """BaselineKey.path includes variant when set."""
    key = BaselineKey(
        library="libfoo", version="1.0.0",
        platform="linux-x86_64", variant="ssl",
    )
    assert key.path == "libfoo/1.0.0/linux-x86_64/ssl"


def test_baseline_key_from_path() -> None:
    """BaselineKey.from_path parses registry paths."""
    key = BaselineKey.from_path("libfoo/1.0.0/linux-x86_64")
    assert key.library == "libfoo"
    assert key.version == "1.0.0"
    assert key.platform == "linux-x86_64"
    assert key.variant == ""


def test_baseline_key_from_path_with_variant() -> None:
    """BaselineKey.from_path parses paths with variant."""
    key = BaselineKey.from_path("libfoo/1.0.0/linux-x86_64/debug")
    assert key.variant == "debug"


def test_baseline_key_from_path_invalid() -> None:
    """BaselineKey.from_path raises on too few parts."""
    with pytest.raises(ValueError, match="Invalid baseline path"):
        BaselineKey.from_path("libfoo/1.0.0")


def test_baseline_key_from_spec() -> None:
    """BaselineKey.from_spec parses colon-separated specs."""
    key = BaselineKey.from_spec("libfoo:1.0.0:linux-x86_64")
    assert key.library == "libfoo"
    assert key.version == "1.0.0"
    assert key.platform == "linux-x86_64"


def test_baseline_key_from_spec_with_variant() -> None:
    """BaselineKey.from_spec parses specs with variant."""
    key = BaselineKey.from_spec("libfoo:1.0.0:linux-x86_64:ssl")
    assert key.variant == "ssl"


def test_baseline_key_from_spec_invalid() -> None:
    """BaselineKey.from_spec raises on too few parts."""
    with pytest.raises(ValueError, match="Invalid baseline spec"):
        BaselineKey.from_spec("libfoo:1.0.0")


# ---------------------------------------------------------------------------
# Tests: BaselineMetadata
# ---------------------------------------------------------------------------


def test_baseline_metadata_create() -> None:
    """BaselineMetadata.create computes checksum."""
    meta = BaselineMetadata.create('{"test": true}')
    assert meta.checksum != ""
    assert meta.abicheck_version != ""
    assert meta.created_at != ""
    assert meta.verify_checksum('{"test": true}')
    assert not meta.verify_checksum('{"test": false}')


def test_baseline_metadata_roundtrip() -> None:
    """BaselineMetadata serializes and deserializes."""
    meta = BaselineMetadata.create('{"test": true}', git_commit="abc123")
    data = meta.to_dict()
    restored = BaselineMetadata.from_dict(data)
    assert restored.checksum == meta.checksum
    assert restored.git_commit == "abc123"
    assert restored.abicheck_version == meta.abicheck_version


# ---------------------------------------------------------------------------
# Tests: FilesystemRegistry
# ---------------------------------------------------------------------------


def test_push_and_pull(
    registry: FilesystemRegistry,
    sample_snapshot: AbiSnapshot,
) -> None:
    """Push then pull a baseline returns the same snapshot."""
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    ref = registry.push(key, sample_snapshot)
    assert "libfoo" in ref

    result = registry.pull(key)
    assert result is not None
    snapshot, meta = result
    assert snapshot.library == "libfoo.so"
    assert snapshot.version == "1.0.0"
    assert len(snapshot.functions) == 1
    assert meta.checksum != ""


def test_pull_nonexistent(registry: FilesystemRegistry) -> None:
    """Pull of a nonexistent key returns None."""
    key = BaselineKey(library="libfoo", version="999", platform="linux-x86_64")
    assert registry.pull(key) is None


def test_list_empty(registry: FilesystemRegistry) -> None:
    """Listing an empty registry returns empty list."""
    assert registry.list() == []


def test_list_baselines(
    registry: FilesystemRegistry,
    sample_snapshot: AbiSnapshot,
) -> None:
    """List returns all pushed baselines."""
    keys_to_push = [
        BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64"),
        BaselineKey(library="libfoo", version="2.0.0", platform="linux-x86_64"),
        BaselineKey(library="libbar", version="1.0.0", platform="linux-x86_64"),
    ]
    for key in keys_to_push:
        registry.push(key, sample_snapshot)

    keys = registry.list()
    assert len(keys) == 3

    # Filter by prefix
    foo_keys = registry.list(prefix="libfoo")
    assert len(foo_keys) == 2
    assert all(k.library == "libfoo" for k in foo_keys)


def test_delete_baseline(
    registry: FilesystemRegistry,
    sample_snapshot: AbiSnapshot,
) -> None:
    """Delete removes a baseline."""
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    registry.push(key, sample_snapshot)

    assert registry.delete(key) is True
    assert registry.pull(key) is None
    assert registry.list() == []


def test_delete_nonexistent(registry: FilesystemRegistry) -> None:
    """Delete of nonexistent key returns False."""
    key = BaselineKey(library="libfoo", version="999", platform="linux-x86_64")
    assert registry.delete(key) is False


def test_push_overwrites(
    registry: FilesystemRegistry,
    sample_snapshot: AbiSnapshot,
) -> None:
    """Pushing to the same key overwrites the baseline."""
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")

    registry.push(key, sample_snapshot)
    result1 = registry.pull(key)
    assert result1 is not None

    # Create a different snapshot
    snap2 = AbiSnapshot(library="libfoo.so", version="1.0.0", functions=[])
    registry.push(key, snap2)
    result2 = registry.pull(key)
    assert result2 is not None
    assert len(result2[0].functions) == 0


def test_push_with_variant(
    registry: FilesystemRegistry,
    sample_snapshot: AbiSnapshot,
) -> None:
    """Push with variant creates separate entry."""
    key1 = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    key2 = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64", variant="ssl")

    registry.push(key1, sample_snapshot)
    registry.push(key2, sample_snapshot)

    keys = registry.list()
    assert len(keys) == 2
