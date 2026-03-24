"""Tests for snapshot caching layer (5c)."""
import json
from pathlib import Path

from abicheck.model import AbiSnapshot, Function, Visibility
from abicheck.snapshot_cache import _cache_key, lookup, store


def _sample_snap() -> AbiSnapshot:
    return AbiSnapshot(
        library="libfoo.so.1",
        version="1.0",
        functions=[
            Function(
                name="foo_init",
                mangled="_Z8foo_initv",
                return_type="int",
                visibility=Visibility.PUBLIC,
            ),
        ],
    )


class TestCacheKey:
    def test_deterministic(self, tmp_path):
        binary = tmp_path / "lib.so"
        binary.write_bytes(b"ELF content")
        hdr = tmp_path / "foo.h"
        hdr.write_text("#pragma once\n")

        key1 = _cache_key(binary, [hdr], [], "1.0", "c++")
        key2 = _cache_key(binary, [hdr], [], "1.0", "c++")
        assert key1 == key2
        assert len(key1) == 64  # SHA-256 hex

    def test_different_version_different_key(self, tmp_path):
        binary = tmp_path / "lib.so"
        binary.write_bytes(b"ELF content")

        key1 = _cache_key(binary, [], [], "1.0", "c++")
        key2 = _cache_key(binary, [], [], "2.0", "c++")
        assert key1 != key2

    def test_different_content_different_key(self, tmp_path):
        b1 = tmp_path / "lib1.so"
        b1.write_bytes(b"content A")
        b2 = tmp_path / "lib2.so"
        b2.write_bytes(b"content B")

        key1 = _cache_key(b1, [], [], "1.0", "c++")
        key2 = _cache_key(b2, [], [], "1.0", "c++")
        assert key1 != key2

    def test_missing_binary_returns_empty(self, tmp_path):
        key = _cache_key(tmp_path / "nonexistent.so", [], [], "1.0", "c++")
        assert key == ""


class TestLookupStore:
    def test_miss_returns_none(self, tmp_path):
        binary = tmp_path / "lib.so"
        binary.write_bytes(b"content")
        result = lookup(binary, [], [], "1.0", "c++")
        assert result is None

    def test_store_and_lookup_roundtrip(self, tmp_path, monkeypatch):
        # Use a temp cache dir
        cache_dir = tmp_path / "cache"
        import abicheck.snapshot_cache as sc
        monkeypatch.setattr(sc, "_CACHE_DIR", cache_dir)

        binary = tmp_path / "lib.so"
        binary.write_bytes(b"ELF content")

        snap = _sample_snap()
        store(snap, binary, [], [], "1.0", "c++")
        assert cache_dir.exists()
        assert len(list(cache_dir.glob("*.json"))) == 1

        result = lookup(binary, [], [], "1.0", "c++")
        assert result is not None
        assert result.library == "libfoo.so.1"
        assert len(result.functions) == 1

    def test_invalidation_on_content_change(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        import abicheck.snapshot_cache as sc
        monkeypatch.setattr(sc, "_CACHE_DIR", cache_dir)

        binary = tmp_path / "lib.so"
        binary.write_bytes(b"version 1")

        snap = _sample_snap()
        store(snap, binary, [], [], "1.0", "c++")

        # Modify binary content
        binary.write_bytes(b"version 2")
        result = lookup(binary, [], [], "1.0", "c++")
        assert result is None  # cache miss — binary changed


class TestEviction:
    def test_evicts_oldest_entries(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        import abicheck.snapshot_cache as sc
        monkeypatch.setattr(sc, "_CACHE_DIR", cache_dir)
        monkeypatch.setattr(sc, "MAX_ENTRIES", 3)

        snap = _sample_snap()
        # Create 5 cache entries
        for i in range(5):
            binary = tmp_path / f"lib{i}.so"
            binary.write_bytes(f"content {i}".encode())
            store(snap, binary, [], [], "1.0", "c++")

        # Should have at most MAX_ENTRIES files
        entries = list(cache_dir.glob("*.json"))
        assert len(entries) <= 3
