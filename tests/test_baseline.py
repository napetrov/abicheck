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

import json
from pathlib import Path

import pytest

from abicheck.baseline import (
    BaselineIntegrityError,
    BaselineKey,
    BaselineMetadata,
    FilesystemRegistry,
)
from abicheck.errors import ValidationError
from abicheck.model import AbiSnapshot, Function, Visibility


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_snapshot() -> AbiSnapshot:
    return AbiSnapshot(
        library="libfoo.so",
        version="1.0.0",
        functions=[
            Function(name="foo", mangled="foo", return_type="void",
                     visibility=Visibility.PUBLIC),
        ],
    )


@pytest.fixture()
def registry(tmp_path: Path) -> FilesystemRegistry:
    return FilesystemRegistry(tmp_path / "baselines")


# ---------------------------------------------------------------------------
# Tests: BaselineKey path traversal protection
# ---------------------------------------------------------------------------


def test_baseline_key_rejects_path_traversal() -> None:
    """Path traversal sequences are rejected."""
    with pytest.raises(ValidationError, match="must not contain"):
        BaselineKey(library="../../etc", version="1.0", platform="x")

    with pytest.raises(ValidationError, match="must not contain"):
        BaselineKey(library="lib", version="../..", platform="x")


def test_baseline_key_rejects_invalid_chars() -> None:
    """Special characters in key fields are rejected."""
    with pytest.raises(ValidationError, match="invalid characters"):
        BaselineKey(library="lib foo", version="1.0", platform="x")

    with pytest.raises(ValidationError, match="invalid characters"):
        BaselineKey(library="lib/foo", version="1.0", platform="x")

    with pytest.raises(ValidationError, match="must not be empty"):
        BaselineKey(library="", version="1.0", platform="x")


def test_baseline_key_accepts_valid_names() -> None:
    """Valid names with dots, hyphens, underscores, plus are accepted."""
    key = BaselineKey(library="libfoo-2.0", version="1.0.0-rc1", platform="linux-x86_64")
    assert key.library == "libfoo-2.0"

    key2 = BaselineKey(library="lib_foo+ssl", version="v2.0", platform="linux-x86_64")
    assert key2.library == "lib_foo+ssl"


# ---------------------------------------------------------------------------
# Tests: BaselineKey parsing
# ---------------------------------------------------------------------------


def test_baseline_key_path() -> None:
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    assert key.path == "libfoo/1.0.0/linux-x86_64"


def test_baseline_key_path_with_variant() -> None:
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64", variant="ssl")
    assert key.path == "libfoo/1.0.0/linux-x86_64/ssl"


def test_baseline_key_from_path() -> None:
    key = BaselineKey.from_path("libfoo/1.0.0/linux-x86_64")
    assert key.library == "libfoo"
    assert key.version == "1.0.0"
    assert key.platform == "linux-x86_64"
    assert key.variant == ""


def test_baseline_key_from_path_with_variant() -> None:
    key = BaselineKey.from_path("libfoo/1.0.0/linux-x86_64/debug")
    assert key.variant == "debug"


def test_baseline_key_from_path_invalid() -> None:
    with pytest.raises(ValidationError, match="Invalid baseline path"):
        BaselineKey.from_path("libfoo/1.0.0")


def test_baseline_key_from_path_too_many_segments() -> None:
    with pytest.raises(ValidationError, match="Too many segments"):
        BaselineKey.from_path("a/b/c/d/e")


def test_baseline_key_from_spec() -> None:
    key = BaselineKey.from_spec("libfoo:1.0.0:linux-x86_64")
    assert key.library == "libfoo"


def test_baseline_key_from_spec_with_variant() -> None:
    key = BaselineKey.from_spec("libfoo:1.0.0:linux-x86_64:ssl")
    assert key.variant == "ssl"


def test_baseline_key_from_spec_invalid() -> None:
    with pytest.raises(ValidationError, match="Invalid baseline spec"):
        BaselineKey.from_spec("libfoo:1.0.0")


def test_baseline_key_from_spec_too_many() -> None:
    with pytest.raises(ValidationError, match="Too many segments"):
        BaselineKey.from_spec("a:b:c:d:e")


# ---------------------------------------------------------------------------
# Tests: BaselineMetadata checksum
# ---------------------------------------------------------------------------


def test_baseline_metadata_create() -> None:
    meta = BaselineMetadata.create('{"test": true}')
    assert meta.checksum is not None
    assert meta.checksum != ""
    assert meta.verify_checksum('{"test": true}')
    assert not meta.verify_checksum('{"test": false}')


def test_baseline_metadata_empty_checksum_fails() -> None:
    """Empty string checksum is treated as mismatch, not bypass."""
    meta = BaselineMetadata(checksum="")
    assert not meta.verify_checksum('{"anything": true}')


def test_baseline_metadata_none_checksum_passes() -> None:
    """None checksum (legacy metadata) passes verification."""
    meta = BaselineMetadata(checksum=None)
    assert meta.verify_checksum('{"anything": true}')


def test_baseline_metadata_roundtrip() -> None:
    meta = BaselineMetadata.create('{"test": true}', git_commit="abc123")
    data = meta.to_dict()
    restored = BaselineMetadata.from_dict(data)
    assert restored.checksum == meta.checksum
    assert restored.git_commit == "abc123"
    assert restored.abicheck_version == meta.abicheck_version


def test_baseline_metadata_from_dict_none_checksum() -> None:
    """from_dict with checksum=None produces None, not 'None' string."""
    data = {"checksum": None}
    meta = BaselineMetadata.from_dict(data)
    assert meta.checksum is None


def test_baseline_metadata_from_dict_missing_checksum() -> None:
    """from_dict without checksum key produces None."""
    meta = BaselineMetadata.from_dict({})
    assert meta.checksum is None


# ---------------------------------------------------------------------------
# Tests: FilesystemRegistry
# ---------------------------------------------------------------------------


def test_push_and_pull(registry: FilesystemRegistry, sample_snapshot: AbiSnapshot) -> None:
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    ref = registry.push(key, sample_snapshot)
    assert "libfoo" in ref

    result = registry.pull(key)
    assert result is not None
    snapshot, meta = result
    assert snapshot.library == "libfoo.so"
    assert snapshot.version == "1.0.0"
    assert len(snapshot.functions) == 1
    assert meta.checksum is not None


def test_pull_nonexistent(registry: FilesystemRegistry) -> None:
    key = BaselineKey(library="libfoo", version="999", platform="linux-x86_64")
    assert registry.pull(key) is None


def test_pull_checksum_mismatch_raises(
    registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
) -> None:
    """Tampered snapshots raise BaselineIntegrityError."""
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    registry.push(key, sample_snapshot)

    # Tamper with the snapshot file
    key_dir = registry._key_dir(key)
    snap_path = key_dir / "snapshot.json"
    snap_path.write_text('{"tampered": true}', encoding="utf-8")

    with pytest.raises(BaselineIntegrityError, match="Checksum mismatch"):
        registry.pull(key)


def test_pull_missing_metadata_still_works(
    registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
) -> None:
    """Pull works when metadata.json is missing (legacy/corrupt)."""
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    registry.push(key, sample_snapshot)

    # Delete metadata.json
    key_dir = registry._key_dir(key)
    (key_dir / "metadata.json").unlink()

    result = registry.pull(key)
    assert result is not None
    assert result[1].checksum is None  # no metadata → no checksum


def test_list_empty(registry: FilesystemRegistry) -> None:
    assert registry.list() == []


def test_list_baselines(
    registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
) -> None:
    keys_to_push = [
        BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64"),
        BaselineKey(library="libfoo", version="2.0.0", platform="linux-x86_64"),
        BaselineKey(library="libbar", version="1.0.0", platform="linux-x86_64"),
    ]
    for key in keys_to_push:
        registry.push(key, sample_snapshot)

    keys = registry.list()
    assert len(keys) == 3

    foo_keys = registry.list(prefix="libfoo")
    assert len(foo_keys) == 2
    assert all(k.library == "libfoo" for k in foo_keys)


def test_delete_baseline(
    registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
) -> None:
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    registry.push(key, sample_snapshot)
    assert registry.delete(key) is True
    assert registry.pull(key) is None
    assert registry.list() == []


def test_delete_cleans_empty_parents(
    registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
) -> None:
    """Delete removes empty parent directories up to root."""
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    registry.push(key, sample_snapshot)
    registry.delete(key)
    # The library directory should be cleaned up
    assert not (registry.root / "libfoo").exists()


def test_delete_nonexistent(registry: FilesystemRegistry) -> None:
    key = BaselineKey(library="libfoo", version="999", platform="linux-x86_64")
    assert registry.delete(key) is False


def test_push_overwrites(
    registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
) -> None:
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    registry.push(key, sample_snapshot)

    snap2 = AbiSnapshot(library="libfoo.so", version="1.0.0", functions=[])
    registry.push(key, snap2)
    result = registry.pull(key)
    assert result is not None
    assert len(result[0].functions) == 0


def test_push_with_variant(
    registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
) -> None:
    key1 = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
    key2 = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64", variant="ssl")

    registry.push(key1, sample_snapshot)
    registry.push(key2, sample_snapshot)

    keys = registry.list()
    assert len(keys) == 2


def test_key_dir_escape_rejected(registry: FilesystemRegistry) -> None:
    """Defense-in-depth: _key_dir rejects paths that escape root."""
    # This shouldn't even be reachable due to __post_init__ validation,
    # but the _key_dir check is there as defense-in-depth.
    # We test __post_init__ validation directly:
    with pytest.raises(ValidationError):
        BaselineKey(library="..%2F..%2Fetc", version="x", platform="x")
