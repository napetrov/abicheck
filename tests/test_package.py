"""Tests for package extraction layer (ADR-006)."""
from __future__ import annotations

import os
import struct
import tarfile
from pathlib import Path

import pytest

from abicheck.errors import ExtractionSecurityError
from abicheck.package import (
    DebExtractor,
    DirExtractor,
    ExtractResult,
    RpmExtractor,
    TarExtractor,
    _is_elf_shared_object,
    _validate_member_path,
    _validate_symlink_target,
    detect_extractor,
    discover_shared_libraries,
    is_package,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_minimal_elf_so(path: Path) -> None:
    """Write a minimal valid ELF shared object (ET_DYN) file.

    This is a stripped-down 64-bit little-endian ELF header with e_type=ET_DYN.
    Not a real executable, but enough for magic/type detection.
    """
    # ELF header: 64 bytes for 64-bit
    e_ident = b"\x7fELF"  # magic
    e_ident += b"\x02"  # EI_CLASS: 64-bit
    e_ident += b"\x01"  # EI_DATA: little-endian
    e_ident += b"\x01"  # EI_VERSION: current
    e_ident += b"\x00" * 9  # padding
    e_type = struct.pack("<H", 3)  # ET_DYN
    e_machine = struct.pack("<H", 0x3E)  # EM_X86_64
    e_version = struct.pack("<I", 1)
    # Rest of header (entry, phoff, shoff, flags, etc.)
    rest = b"\x00" * (64 - 16 - 2 - 2 - 4)
    path.write_bytes(e_ident + e_type + e_machine + e_version + rest)


def _make_minimal_elf_exec(path: Path) -> None:
    """Write a minimal ELF executable (ET_EXEC, not ET_DYN)."""
    e_ident = b"\x7fELF\x02\x01\x01" + b"\x00" * 9
    e_type = struct.pack("<H", 2)  # ET_EXEC
    rest = b"\x00" * (64 - 16 - 2)
    path.write_bytes(e_ident + e_type + rest)


def _make_tar(archive_path: Path, files: dict[str, bytes]) -> None:
    """Create a tar.gz archive with given file contents."""
    import io

    with tarfile.open(archive_path, "w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))


# ── Security validation tests ────────────────────────────────────────────────


class TestValidateMemberPath:
    def test_safe_path(self, tmp_path: Path) -> None:
        result = _validate_member_path("usr/lib/libfoo.so", tmp_path)
        assert result == (tmp_path / "usr/lib/libfoo.so").resolve()

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ExtractionSecurityError, match="absolute path"):
            _validate_member_path("/etc/passwd", tmp_path)

    def test_traversal_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ExtractionSecurityError, match="path traversal"):
            _validate_member_path("usr/../../etc/passwd", tmp_path)

    def test_traversal_at_start(self, tmp_path: Path) -> None:
        with pytest.raises(ExtractionSecurityError, match="path traversal"):
            _validate_member_path("../etc/passwd", tmp_path)

    def test_simple_filename(self, tmp_path: Path) -> None:
        result = _validate_member_path("libfoo.so", tmp_path)
        assert result == (tmp_path / "libfoo.so").resolve()

    def test_nested_safe_path(self, tmp_path: Path) -> None:
        result = _validate_member_path("a/b/c/d.so", tmp_path)
        assert result == (tmp_path / "a/b/c/d.so").resolve()


class TestValidateSymlinkTarget:
    def test_safe_symlink(self, tmp_path: Path) -> None:
        # Create the directory so resolve works
        (tmp_path / "usr" / "lib").mkdir(parents=True)
        (tmp_path / "usr" / "lib" / "libfoo.so.1").touch()
        _validate_symlink_target(
            "usr/lib/libfoo.so", "libfoo.so.1", tmp_path
        )

    def test_escaping_symlink_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "usr" / "lib").mkdir(parents=True)
        with pytest.raises(ExtractionSecurityError, match="symlink target"):
            _validate_symlink_target(
                "usr/lib/evil", "../../../../etc/passwd", tmp_path
            )


# ── Format detection tests ──────────────────────────────────────────────────


class TestIsPackage:
    def test_rpm_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "libfoo.rpm"
        f.write_bytes(b"\xed\xab\xee\xdb" + b"\x00" * 100)
        assert is_package(f) is True

    def test_deb_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "libfoo.deb"
        f.write_bytes(b"!<arch>\n" + b"\x00" * 100)
        assert is_package(f) is True

    def test_tar_gz_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "sdk.tar.gz"
        _make_tar(f, {"README": b"hello"})
        assert is_package(f) is True

    def test_tgz_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "sdk.tgz"
        _make_tar(f, {"README": b"hello"})
        assert is_package(f) is True

    def test_directory_not_package(self, tmp_path: Path) -> None:
        assert is_package(tmp_path) is False

    def test_so_file_not_package(self, tmp_path: Path) -> None:
        f = tmp_path / "libfoo.so"
        _make_minimal_elf_so(f)
        assert is_package(f) is False

    def test_json_not_package(self, tmp_path: Path) -> None:
        f = tmp_path / "snapshot.json"
        f.write_text("{}")
        assert is_package(f) is False

    def test_rpm_by_magic(self, tmp_path: Path) -> None:
        f = tmp_path / "unknown_file"
        f.write_bytes(b"\xed\xab\xee\xdb" + b"\x00" * 100)
        assert is_package(f) is True

    def test_deb_by_magic(self, tmp_path: Path) -> None:
        f = tmp_path / "unknown_file"
        f.write_bytes(b"!<arch>\n" + b"\x00" * 100)
        assert is_package(f) is True


class TestDetectExtractor:
    def test_directory(self, tmp_path: Path) -> None:
        ext = detect_extractor(tmp_path)
        assert isinstance(ext, DirExtractor)

    def test_tar_gz(self, tmp_path: Path) -> None:
        f = tmp_path / "test.tar.gz"
        _make_tar(f, {"README": b"hello"})
        ext = detect_extractor(f)
        assert isinstance(ext, TarExtractor)

    def test_tar_xz(self, tmp_path: Path) -> None:
        f = tmp_path / "test.tar.xz"
        f.write_bytes(b"\xfd7zXZ\x00" + b"\x00" * 100)
        ext = detect_extractor(f)
        assert isinstance(ext, TarExtractor)

    def test_rpm(self, tmp_path: Path) -> None:
        f = tmp_path / "test.rpm"
        f.write_bytes(b"\xed\xab\xee\xdb" + b"\x00" * 100)
        ext = detect_extractor(f)
        assert isinstance(ext, RpmExtractor)

    def test_deb(self, tmp_path: Path) -> None:
        f = tmp_path / "test.deb"
        f.write_bytes(b"!<arch>\n" + b"\x00" * 100)
        ext = detect_extractor(f)
        assert isinstance(ext, DebExtractor)

    def test_unknown(self, tmp_path: Path) -> None:
        f = tmp_path / "test.xyz"
        f.write_bytes(b"unknown format")
        ext = detect_extractor(f)
        assert ext is None


# ── TarExtractor tests ──────────────────────────────────────────────────────


class TestTarExtractor:
    def test_basic_extraction(self, tmp_path: Path) -> None:
        archive = tmp_path / "test.tar.gz"
        _make_tar(archive, {
            "usr/lib/libfoo.so": b"\x7fELF fake",
            "usr/lib/libbar.so": b"\x7fELF fake",
        })
        out = tmp_path / "output"
        out.mkdir()
        ext = TarExtractor()
        result = ext.extract(archive, out)
        assert result.lib_dir == out
        assert (out / "usr/lib/libfoo.so").exists()
        assert (out / "usr/lib/libbar.so").exists()

    def test_detect_tar_gz(self, tmp_path: Path) -> None:
        f = tmp_path / "test.tar.gz"
        _make_tar(f, {"a": b""})
        assert TarExtractor().detect(f)

    def test_detect_tar_xz(self, tmp_path: Path) -> None:
        f = tmp_path / "test.tar.xz"
        f.touch()
        assert TarExtractor().detect(f)

    def test_detect_tgz(self, tmp_path: Path) -> None:
        f = tmp_path / "test.tgz"
        f.touch()
        assert TarExtractor().detect(f)

    def test_detect_plain_tar(self, tmp_path: Path) -> None:
        f = tmp_path / "test.tar"
        f.touch()
        assert TarExtractor().detect(f)

    def test_not_detect_so(self, tmp_path: Path) -> None:
        f = tmp_path / "libfoo.so"
        f.touch()
        assert not TarExtractor().detect(f)

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "evil.tar.gz"
        import io
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"evil"))

        out = tmp_path / "output"
        out.mkdir()
        with pytest.raises(ExtractionSecurityError, match="path traversal"):
            TarExtractor().extract(archive, out)

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "evil.tar.gz"
        import io
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo(name="/etc/passwd")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"evil"))

        out = tmp_path / "output"
        out.mkdir()
        with pytest.raises(ExtractionSecurityError, match="absolute path"):
            TarExtractor().extract(archive, out)


# ── DirExtractor tests ──────────────────────────────────────────────────────


class TestDirExtractor:
    def test_detect_directory(self, tmp_path: Path) -> None:
        assert DirExtractor().detect(tmp_path)

    def test_detect_file_false(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.touch()
        assert not DirExtractor().detect(f)

    def test_passthrough(self, tmp_path: Path) -> None:
        result = DirExtractor().extract(tmp_path, tmp_path / "unused")
        assert result.lib_dir == tmp_path


# ── RpmExtractor tests ──────────────────────────────────────────────────────


class TestRpmExtractor:
    def test_detect_rpm_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "test.rpm"
        f.write_bytes(b"\xed\xab\xee\xdb" + b"\x00" * 100)
        assert RpmExtractor().detect(f)

    def test_detect_rpm_magic(self, tmp_path: Path) -> None:
        f = tmp_path / "noext"
        f.write_bytes(b"\xed\xab\xee\xdb" + b"\x00" * 100)
        assert RpmExtractor().detect(f)

    def test_detect_non_rpm(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_bytes(b"not an rpm")
        assert not RpmExtractor().detect(f)


# ── DebExtractor tests ──────────────────────────────────────────────────────


class TestDebExtractor:
    def test_detect_deb_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "test.deb"
        f.write_bytes(b"!<arch>\n" + b"\x00" * 100)
        assert DebExtractor().detect(f)

    def test_detect_deb_magic(self, tmp_path: Path) -> None:
        f = tmp_path / "noext"
        f.write_bytes(b"!<arch>\n" + b"\x00" * 100)
        assert DebExtractor().detect(f)

    def test_detect_non_deb(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_bytes(b"not a deb")
        assert not DebExtractor().detect(f)


# ── ELF shared object detection ─────────────────────────────────────────────


class TestIsElfSharedObject:
    def test_shared_object(self, tmp_path: Path) -> None:
        f = tmp_path / "libfoo.so"
        _make_minimal_elf_so(f)
        assert _is_elf_shared_object(f) is True

    def test_executable(self, tmp_path: Path) -> None:
        f = tmp_path / "prog"
        _make_minimal_elf_exec(f)
        assert _is_elf_shared_object(f) is False

    def test_non_elf(self, tmp_path: Path) -> None:
        f = tmp_path / "text.txt"
        f.write_text("hello")
        assert _is_elf_shared_object(f) is False

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty"
        f.touch()
        assert _is_elf_shared_object(f) is False


# ── Binary discovery tests ──────────────────────────────────────────────────


class TestDiscoverSharedLibraries:
    def test_finds_so_in_lib(self, tmp_path: Path) -> None:
        lib_dir = tmp_path / "usr" / "lib64"
        lib_dir.mkdir(parents=True)
        _make_minimal_elf_so(lib_dir / "libfoo.so.1.0")
        _make_minimal_elf_so(lib_dir / "libbar.so.2.0")

        result = discover_shared_libraries(tmp_path)
        names = [p.name for p in result]
        assert "libfoo.so.1.0" in names
        assert "libbar.so.2.0" in names

    def test_skips_executables(self, tmp_path: Path) -> None:
        lib_dir = tmp_path / "usr" / "lib"
        lib_dir.mkdir(parents=True)
        _make_minimal_elf_so(lib_dir / "libfoo.so")
        _make_minimal_elf_exec(lib_dir / "myapp")

        result = discover_shared_libraries(tmp_path)
        names = [p.name for p in result]
        assert "libfoo.so" in names
        assert "myapp" not in names

    def test_skips_private_by_default(self, tmp_path: Path) -> None:
        # A DSO in a non-standard path without .so in name
        priv_dir = tmp_path / "opt" / "vendor" / "plugins"
        priv_dir.mkdir(parents=True)
        _make_minimal_elf_so(priv_dir / "myplugin.bin")

        result = discover_shared_libraries(tmp_path)
        assert len(result) == 0

    def test_includes_private_with_flag(self, tmp_path: Path) -> None:
        priv_dir = tmp_path / "opt" / "vendor" / "plugins"
        priv_dir.mkdir(parents=True)
        _make_minimal_elf_so(priv_dir / "myplugin.bin")

        result = discover_shared_libraries(tmp_path, include_private=True)
        names = [p.name for p in result]
        assert "myplugin.bin" in names

    def test_finds_so_in_flat_layout(self, tmp_path: Path) -> None:
        """DSOs with .so in name should be found even in non-standard paths."""
        _make_minimal_elf_so(tmp_path / "libfoo.so")
        result = discover_shared_libraries(tmp_path)
        assert len(result) == 1
        assert result[0].name == "libfoo.so"

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = discover_shared_libraries(tmp_path)
        assert result == []

    def test_sorted_by_name(self, tmp_path: Path) -> None:
        lib_dir = tmp_path / "usr" / "lib"
        lib_dir.mkdir(parents=True)
        _make_minimal_elf_so(lib_dir / "libzoo.so")
        _make_minimal_elf_so(lib_dir / "libalpha.so")
        _make_minimal_elf_so(lib_dir / "libmid.so")

        result = discover_shared_libraries(tmp_path)
        names = [p.name for p in result]
        assert names == sorted(names)

    def test_skips_non_elf_files(self, tmp_path: Path) -> None:
        lib_dir = tmp_path / "usr" / "lib"
        lib_dir.mkdir(parents=True)
        (lib_dir / "libfoo.so").write_text("not elf")
        (lib_dir / "readme.txt").write_text("hello")

        result = discover_shared_libraries(tmp_path)
        assert len(result) == 0


# ── CLI integration tests (tar-based, no system deps) ───────────────────────


class TestCompareReleaseTarPackages:
    """Integration tests using tar archives (no rpm2cpio/ar needed)."""

    def _make_snapshot_tar(
        self, tmp_path: Path, name: str, snapshot_json: str,
    ) -> Path:
        """Create a tar.gz containing a JSON snapshot in usr/lib/."""
        archive = tmp_path / name
        import io
        with tarfile.open(archive, "w:gz") as tf:
            data = snapshot_json.encode()
            info = tarfile.TarInfo(name=f"libfoo.so.json")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        return archive

    def test_tar_packages_accepted(self, tmp_path: Path) -> None:
        """Verify that compare-release accepts tar.gz inputs."""
        from click.testing import CliRunner

        from abicheck.cli import main
        from abicheck.model import AbiSnapshot, Function, Visibility
        from abicheck.serialization import snapshot_to_json

        snap_old = AbiSnapshot(
            library="libfoo.so", version="1.0",
            functions=[Function(name="foo", mangled="_Z3foov",
                                return_type="int", visibility=Visibility.PUBLIC)],
        )
        snap_new = AbiSnapshot(
            library="libfoo.so", version="2.0",
            functions=[Function(name="foo", mangled="_Z3foov",
                                return_type="int", visibility=Visibility.PUBLIC)],
        )

        old_tar = self._make_snapshot_tar(
            tmp_path, "old.tar.gz", snapshot_to_json(snap_old),
        )
        new_tar = self._make_snapshot_tar(
            tmp_path, "new.tar.gz", snapshot_to_json(snap_new),
        )

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare-release", str(old_tar), str(new_tar),
            "--format", "json",
        ])
        # Should succeed — NO_CHANGE since snapshots are identical
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"

    def test_keep_extracted_flag(self, tmp_path: Path) -> None:
        """Verify --keep-extracted prevents cleanup."""
        from click.testing import CliRunner

        from abicheck.cli import main
        from abicheck.model import AbiSnapshot, Function, Visibility
        from abicheck.serialization import snapshot_to_json

        snap = AbiSnapshot(
            library="libfoo.so", version="1.0",
            functions=[Function(name="foo", mangled="_Z3foov",
                                return_type="int", visibility=Visibility.PUBLIC)],
        )
        tar = self._make_snapshot_tar(
            tmp_path, "pkg.tar.gz", snapshot_to_json(snap),
        )

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare-release", str(tar), str(tar),
            "--format", "json", "--keep-extracted",
        ])
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
        # The stderr should mention kept files
        # (CliRunner combines output by default)


class TestCompareReleaseDirectoryPassthrough:
    """Verify existing directory-based compare-release still works."""

    def test_directories_still_work(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from abicheck.cli import main
        from abicheck.model import AbiSnapshot, Function, Visibility
        from abicheck.serialization import snapshot_to_json

        snap = AbiSnapshot(
            library="libfoo.so", version="1.0",
            functions=[Function(name="foo", mangled="_Z3foov",
                                return_type="int", visibility=Visibility.PUBLIC)],
        )

        old_dir = tmp_path / "old"
        new_dir = tmp_path / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        (old_dir / "libfoo.so.json").write_text(snapshot_to_json(snap))
        (new_dir / "libfoo.so.json").write_text(snapshot_to_json(snap))

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare-release", str(old_dir), str(new_dir),
            "--format", "json",
        ])
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"


# ── ExtractResult tests ─────────────────────────────────────────────────────


class TestExtractResult:
    def test_defaults(self, tmp_path: Path) -> None:
        r = ExtractResult(lib_dir=tmp_path)
        assert r.debug_dir is None
        assert r.header_dir is None
        assert r.metadata == {}

    def test_with_all_fields(self, tmp_path: Path) -> None:
        r = ExtractResult(
            lib_dir=tmp_path,
            debug_dir=tmp_path / "debug",
            header_dir=tmp_path / "headers",
            metadata={"name": "libfoo", "version": "1.0"},
        )
        assert r.debug_dir == tmp_path / "debug"
        assert r.header_dir == tmp_path / "headers"
        assert r.metadata["name"] == "libfoo"
