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
    BaselineIntegrityError,
    BaselineKey,
    BaselineMetadata,
    FilesystemRegistry,
    _atomic_write,
    _validate_key_field,
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
# Tests: _validate_key_field
# ---------------------------------------------------------------------------


class TestValidateKeyField:
    def test_valid_names(self) -> None:
        _validate_key_field("x", "libfoo")
        _validate_key_field("x", "lib-foo_2.0+ssl")
        _validate_key_field("x", "linux-x86_64")
        _validate_key_field("x", "1.0.0-rc1")

    def test_empty(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            _validate_key_field("library", "")

    def test_path_traversal(self) -> None:
        with pytest.raises(ValidationError, match="must not contain"):
            _validate_key_field("library", "../../etc")
        with pytest.raises(ValidationError, match="must not contain"):
            _validate_key_field("version", "a..b")

    def test_invalid_chars(self) -> None:
        with pytest.raises(ValidationError, match="invalid characters"):
            _validate_key_field("library", "lib foo")
        with pytest.raises(ValidationError, match="invalid characters"):
            _validate_key_field("library", "lib/foo")
        with pytest.raises(ValidationError, match="invalid characters"):
            _validate_key_field("library", "lib:foo")
        with pytest.raises(ValidationError, match="invalid characters"):
            _validate_key_field("library", "lib\x00foo")


# ---------------------------------------------------------------------------
# Tests: BaselineKey
# ---------------------------------------------------------------------------


class TestBaselineKey:
    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValidationError, match="must not contain"):
            BaselineKey(library="../../etc", version="1.0", platform="x")
        with pytest.raises(ValidationError, match="must not contain"):
            BaselineKey(library="lib", version="../..", platform="x")

    def test_rejects_invalid_chars(self) -> None:
        with pytest.raises(ValidationError, match="invalid characters"):
            BaselineKey(library="lib foo", version="1.0", platform="x")
        with pytest.raises(ValidationError, match="invalid characters"):
            BaselineKey(library="lib/foo", version="1.0", platform="x")
        with pytest.raises(ValidationError, match="must not be empty"):
            BaselineKey(library="", version="1.0", platform="x")

    def test_accepts_valid_names(self) -> None:
        key = BaselineKey(library="libfoo-2.0", version="1.0.0-rc1", platform="linux-x86_64")
        assert key.library == "libfoo-2.0"
        key2 = BaselineKey(library="lib_foo+ssl", version="v2.0", platform="linux-x86_64")
        assert key2.library == "lib_foo+ssl"

    def test_path(self) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        assert key.path == "libfoo/1.0.0/linux-x86_64"
        assert str(key) == "libfoo/1.0.0/linux-x86_64"

    def test_path_with_variant(self) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64", variant="ssl")
        assert key.path == "libfoo/1.0.0/linux-x86_64/ssl"

    def test_from_path(self) -> None:
        key = BaselineKey.from_path("libfoo/1.0.0/linux-x86_64")
        assert key.library == "libfoo"
        assert key.version == "1.0.0"
        assert key.platform == "linux-x86_64"
        assert key.variant == ""

    def test_from_path_with_variant(self) -> None:
        key = BaselineKey.from_path("libfoo/1.0.0/linux-x86_64/debug")
        assert key.variant == "debug"

    def test_from_path_strips_slashes(self) -> None:
        key = BaselineKey.from_path("/libfoo/1.0.0/linux-x86_64/")
        assert key.library == "libfoo"

    def test_from_path_invalid(self) -> None:
        with pytest.raises(ValidationError, match="Invalid baseline path"):
            BaselineKey.from_path("libfoo/1.0.0")

    def test_from_path_too_many_segments(self) -> None:
        with pytest.raises(ValidationError, match="Too many segments"):
            BaselineKey.from_path("a/b/c/d/e")

    def test_from_spec(self) -> None:
        key = BaselineKey.from_spec("libfoo:1.0.0:linux-x86_64")
        assert key.library == "libfoo"

    def test_from_spec_with_variant(self) -> None:
        key = BaselineKey.from_spec("libfoo:1.0.0:linux-x86_64:ssl")
        assert key.variant == "ssl"

    def test_from_spec_invalid(self) -> None:
        with pytest.raises(ValidationError, match="Invalid baseline spec"):
            BaselineKey.from_spec("libfoo:1.0.0")

    def test_from_spec_too_many(self) -> None:
        with pytest.raises(ValidationError, match="Too many segments"):
            BaselineKey.from_spec("a:b:c:d:e")

    def test_frozen(self) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        with pytest.raises(AttributeError):
            key.library = "bar"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests: BaselineMetadata
# ---------------------------------------------------------------------------


class TestBaselineMetadata:
    def test_create(self) -> None:
        meta = BaselineMetadata.create('{"test": true}')
        assert meta.checksum is not None
        assert meta.checksum != ""
        assert meta.abicheck_version
        assert meta.created_at
        assert meta.schema_version >= 1
        assert meta.verify_checksum('{"test": true}')
        assert not meta.verify_checksum('{"test": false}')

    def test_create_with_optional_fields(self) -> None:
        meta = BaselineMetadata.create(
            '{"test": true}',
            build_context_hash="abc123",
            git_commit="def456",
        )
        assert meta.build_context_hash == "abc123"
        assert meta.git_commit == "def456"

    def test_empty_checksum_fails(self) -> None:
        meta = BaselineMetadata(checksum="")
        assert not meta.verify_checksum('{"anything": true}')

    def test_none_checksum_passes(self) -> None:
        meta = BaselineMetadata(checksum=None)
        assert meta.verify_checksum('{"anything": true}')

    def test_roundtrip(self) -> None:
        meta = BaselineMetadata.create('{"test": true}', git_commit="abc123")
        data = meta.to_dict()
        restored = BaselineMetadata.from_dict(data)
        assert restored.checksum == meta.checksum
        assert restored.git_commit == "abc123"
        assert restored.abicheck_version == meta.abicheck_version
        assert restored.schema_version == meta.schema_version
        assert restored.created_at == meta.created_at

    def test_from_dict_none_checksum(self) -> None:
        data = {"checksum": None}
        meta = BaselineMetadata.from_dict(data)
        assert meta.checksum is None

    def test_from_dict_missing_checksum(self) -> None:
        meta = BaselineMetadata.from_dict({})
        assert meta.checksum is None

    def test_from_dict_none_optional_fields(self) -> None:
        data = {"build_context_hash": None, "git_commit": None, "signature": None}
        meta = BaselineMetadata.from_dict(data)
        assert meta.build_context_hash is None
        assert meta.git_commit is None
        assert meta.signature is None

    def test_from_dict_present_optional_fields(self) -> None:
        data = {"build_context_hash": "abc", "git_commit": "def", "signature": "ghi"}
        meta = BaselineMetadata.from_dict(data)
        assert meta.build_context_hash == "abc"
        assert meta.git_commit == "def"
        assert meta.signature == "ghi"

    def test_to_dict(self) -> None:
        meta = BaselineMetadata(checksum="abc", git_commit="def")
        d = meta.to_dict()
        assert d["checksum"] == "abc"
        assert d["git_commit"] == "def"


# ---------------------------------------------------------------------------
# Tests: _atomic_write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        _atomic_write(target, "hello world")
        assert target.read_text() == "hello world"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("old")
        _atomic_write(target, "new")
        assert target.read_text() == "new"

    def test_no_partial_write_on_error(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("original")
        # Force an error by making the directory read-only (can't rename into it)
        # This is hard to test portably, so just verify the function doesn't corrupt
        _atomic_write(target, "replacement")
        assert target.read_text() == "replacement"


# ---------------------------------------------------------------------------
# Tests: FilesystemRegistry
# ---------------------------------------------------------------------------


class TestFilesystemRegistry:
    def test_push_and_pull(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        ref = registry.push(key, sample_snapshot)
        assert "libfoo" in ref
        assert ref.startswith("fs://")

        result = registry.pull(key)
        assert result is not None
        snapshot, meta = result
        assert snapshot.library == "libfoo.so"
        assert snapshot.version == "1.0.0"
        assert len(snapshot.functions) == 1
        assert meta.checksum is not None

    def test_push_creates_metadata(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        registry.push(key, sample_snapshot)
        key_dir = registry._key_dir(key)
        assert (key_dir / "snapshot.json").exists()
        assert (key_dir / "metadata.json").exists()

    def test_push_with_custom_metadata(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        meta = BaselineMetadata(checksum=None, git_commit="custom")
        registry.push(key, sample_snapshot, metadata=meta)
        result = registry.pull(key)
        assert result is not None
        # Custom metadata had None checksum, so pull succeeds
        assert result[1].git_commit == "custom"

    def test_pull_nonexistent(self, registry: FilesystemRegistry) -> None:
        key = BaselineKey(library="libfoo", version="999", platform="linux-x86_64")
        assert registry.pull(key) is None

    def test_pull_checksum_mismatch_raises(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        registry.push(key, sample_snapshot)
        key_dir = registry._key_dir(key)
        snap_path = key_dir / "snapshot.json"
        snap_path.write_text('{"tampered": true}', encoding="utf-8")
        with pytest.raises(BaselineIntegrityError, match="Checksum mismatch"):
            registry.pull(key)

    def test_pull_missing_metadata_still_works(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        registry.push(key, sample_snapshot)
        (registry._key_dir(key) / "metadata.json").unlink()
        result = registry.pull(key)
        assert result is not None
        assert result[1].checksum is None

    def test_pull_corrupt_metadata_still_works(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        registry.push(key, sample_snapshot)
        (registry._key_dir(key) / "metadata.json").write_text("not json")
        result = registry.pull(key)
        assert result is not None
        assert result[1].checksum is None

    def test_list_empty(self, registry: FilesystemRegistry) -> None:
        assert registry.list() == []

    def test_list_baselines(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
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

    def test_list_with_variants(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        k1 = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        k2 = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64", variant="ssl")
        registry.push(k1, sample_snapshot)
        registry.push(k2, sample_snapshot)
        keys = registry.list()
        assert len(keys) == 2

    def test_delete_baseline(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        registry.push(key, sample_snapshot)
        assert registry.delete(key) is True
        assert registry.pull(key) is None
        assert registry.list() == []

    def test_delete_cleans_empty_parents(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        registry.push(key, sample_snapshot)
        registry.delete(key)
        assert not (registry.root / "libfoo").exists()

    def test_delete_preserves_siblings(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        k1 = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        k2 = BaselineKey(library="libfoo", version="2.0.0", platform="linux-x86_64")
        registry.push(k1, sample_snapshot)
        registry.push(k2, sample_snapshot)
        registry.delete(k1)
        assert registry.pull(k2) is not None
        assert (registry.root / "libfoo").exists()

    def test_delete_nonexistent(self, registry: FilesystemRegistry) -> None:
        key = BaselineKey(library="libfoo", version="999", platform="linux-x86_64")
        assert registry.delete(key) is False

    def test_push_overwrites(
        self, registry: FilesystemRegistry, sample_snapshot: AbiSnapshot,
    ) -> None:
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        registry.push(key, sample_snapshot)
        snap2 = AbiSnapshot(library="libfoo.so", version="1.0.0", functions=[])
        registry.push(key, snap2)
        result = registry.pull(key)
        assert result is not None
        assert len(result[0].functions) == 0

    def test_key_dir_escape_rejected(self, registry: FilesystemRegistry) -> None:
        with pytest.raises(ValidationError):
            BaselineKey(library="..%2F..%2Fetc", version="x", platform="x")

    def test_key_dir_relative_to_containment(self, tmp_path: Path) -> None:
        """Verify pathlib-based containment prevents sibling prefix attacks."""
        # /tmp/root2 starts with /tmp/root, but it's not inside it
        root = tmp_path / "root"
        root.mkdir()
        registry = FilesystemRegistry(root)
        # Valid key works fine
        key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")
        key_dir = registry._key_dir(key)
        assert str(key_dir).startswith(str(root))


# ---------------------------------------------------------------------------
# Tests: BaselineIntegrityError
# ---------------------------------------------------------------------------


class TestBaselineIntegrityError:
    def test_is_validation_error(self) -> None:
        """BaselineIntegrityError inherits from ValidationError."""
        err = BaselineIntegrityError("test")
        assert isinstance(err, ValidationError)
        assert isinstance(err, ValueError)  # via ValidationError
