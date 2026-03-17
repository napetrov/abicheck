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

"""Package extraction layer for compare-release (ADR-006).

Converts RPM, Deb, tar, conda, pip wheel packages into directories that
the existing compare-release pipeline can process.  Also supports
downloading packages by name via apt, yum, and zypper.

The extraction flow is:

    Package → Extract → Directory → [compare-release] → AggregateResult

All extractors enforce strict security checks against path traversal,
symlink escapes, and absolute paths.  See ``_validate_member_path()``
for the mandatory safety contract.
"""
from __future__ import annotations

import logging
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from .errors import ExtractionSecurityError

_log = logging.getLogger(__name__)

# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class ExtractResult:
    """Result of extracting a package."""

    lib_dir: Path  # path to extracted shared libraries
    debug_dir: Path | None = None  # path to extracted debug info
    header_dir: Path | None = None  # path to extracted headers (devel pkg)
    metadata: dict[str, str] = field(default_factory=dict)


# ── Security validation ──────────────────────────────────────────────────────


def _validate_member_path(member_name: str, target_root: Path) -> Path:
    """Validate that an archive member path is safe to extract.

    Raises ExtractionSecurityError if the member contains path traversal,
    absolute paths, or resolves outside the extraction root.
    """
    # Reject absolute paths
    if os.path.isabs(member_name):
        raise ExtractionSecurityError(member_name, "absolute path in archive member")

    # Reject path traversal components
    parts = Path(member_name).parts
    if ".." in parts:
        raise ExtractionSecurityError(member_name, "path traversal via '..' component")

    # Canonicalize and verify destination stays within root
    dest = (target_root / member_name).resolve()
    root_resolved = target_root.resolve()
    try:
        dest.relative_to(root_resolved)
    except ValueError:
        raise ExtractionSecurityError(
            member_name, f"resolved path escapes extraction root: {dest}"
        )

    return dest


def _validate_symlink_target(
    member_name: str, link_target: str, target_root: Path
) -> None:
    """Validate that a symlink target resolves within the extraction root."""
    member_parent = (target_root / member_name).resolve().parent
    resolved = (member_parent / link_target).resolve()
    root_resolved = target_root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise ExtractionSecurityError(
            member_name,
            f"symlink target '{link_target}' resolves outside extraction root: {resolved}",
        )


# ── Protocol ─────────────────────────────────────────────────────────────────


@runtime_checkable
class PackageExtractor(Protocol):
    """Extract package contents to a temporary directory."""

    def extract(self, pkg_path: Path, target_dir: Path) -> ExtractResult:
        """Extract package into target_dir and return extraction result."""
        ...

    def detect(self, pkg_path: Path) -> bool:
        """Return True if this extractor can handle the given path."""
        ...


# ── Tar extractor ────────────────────────────────────────────────────────────


class TarExtractor:
    """Extract tar, tar.gz, tar.xz, tar.bz2, and .tgz archives."""

    def detect(self, pkg_path: Path) -> bool:
        name = pkg_path.name.lower()
        return name.endswith((".tar", ".tar.gz", ".tar.xz", ".tar.bz2", ".tgz"))

    def extract(self, pkg_path: Path, target_dir: Path) -> ExtractResult:
        _log.info("Extracting tar archive: %s", pkg_path)
        self._safe_extract(pkg_path, target_dir)
        return ExtractResult(lib_dir=target_dir)

    @staticmethod
    def _safe_extract(archive_path: Path, target_dir: Path) -> None:
        """Extract tar archive with full security validation on every member."""
        target_root = target_dir.resolve()
        with tarfile.open(archive_path) as tf:
            for member in tf.getmembers():
                _validate_member_path(member.name, target_root)

                if member.issym() or member.islnk():
                    link_target = member.linkname
                    _validate_symlink_target(member.name, link_target, target_root)

            # All members validated — now extract
            # Use data_filter if available (Python 3.12+), otherwise manual
            if sys.version_info >= (3, 12):
                tf.extractall(path=target_dir, filter="data")
            else:
                tf.extractall(path=target_dir)


# ── RPM extractor ────────────────────────────────────────────────────────────

_RPM_MAGIC = b"\xed\xab\xee\xdb"


class RpmExtractor:
    """Extract RPM packages using rpm2cpio + cpio."""

    def detect(self, pkg_path: Path) -> bool:
        name = pkg_path.name.lower()
        if name.endswith(".rpm"):
            return True
        # Check magic bytes
        try:
            with open(pkg_path, "rb") as f:
                return f.read(4) == _RPM_MAGIC
        except OSError:
            return False

    def extract(self, pkg_path: Path, target_dir: Path) -> ExtractResult:
        _log.info("Extracting RPM: %s", pkg_path)
        self._rpm_extract(pkg_path, target_dir)
        self._post_validate(target_dir)
        return ExtractResult(lib_dir=target_dir)

    @staticmethod
    def _rpm_extract(rpm_path: Path, target_dir: Path) -> None:
        """Extract RPM via rpm2cpio | cpio pipeline."""
        rpm2cpio = shutil.which("rpm2cpio")
        cpio = shutil.which("cpio")
        if not rpm2cpio:
            raise RuntimeError(
                "rpm2cpio not found. Install rpm-tools or use a tar archive instead."
            )
        if not cpio:
            raise RuntimeError(
                "cpio not found. Install cpio or use a tar archive instead."
            )

        rpm2cpio_proc = subprocess.Popen(
            [rpm2cpio, str(rpm_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        cpio_proc = subprocess.Popen(
            [cpio, "-id", "--no-absolute-filenames", "--quiet"],
            stdin=rpm2cpio_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(target_dir),
        )
        # Allow rpm2cpio to receive SIGPIPE
        if rpm2cpio_proc.stdout:
            rpm2cpio_proc.stdout.close()
        cpio_out, cpio_err = cpio_proc.communicate()
        rpm2cpio_proc.wait()

        if rpm2cpio_proc.returncode != 0:
            raise RuntimeError(f"rpm2cpio failed (exit {rpm2cpio_proc.returncode})")
        if cpio_proc.returncode != 0:
            err_msg = cpio_err.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"cpio extraction failed: {err_msg}")

    @staticmethod
    def _post_validate(target_dir: Path) -> None:
        """Post-extraction validation: check no paths escape root."""
        root = target_dir.resolve()
        for dirpath, _dirnames, filenames in os.walk(target_dir, followlinks=False):
            for fn in filenames:
                full = Path(dirpath, fn).resolve()
                try:
                    full.relative_to(root)
                except ValueError:
                    raise ExtractionSecurityError(
                        str(full), "extracted path escapes extraction root"
                    )
            # Also check symlinks in directory entries
            dp = Path(dirpath)
            for fn in filenames:
                fp = dp / fn
                if fp.is_symlink():
                    link_target = os.readlink(fp)
                    resolved = fp.resolve()
                    try:
                        resolved.relative_to(root)
                    except ValueError:
                        raise ExtractionSecurityError(
                            str(fp.relative_to(target_dir)),
                            f"symlink target '{link_target}' escapes extraction root",
                        )


# ── Deb extractor ────────────────────────────────────────────────────────────

_DEB_MAGIC = b"!<arch>\n"


class DebExtractor:
    """Extract Debian packages using ar + tar."""

    def detect(self, pkg_path: Path) -> bool:
        name = pkg_path.name.lower()
        if name.endswith(".deb"):
            return True
        try:
            with open(pkg_path, "rb") as f:
                return f.read(8) == _DEB_MAGIC
        except OSError:
            return False

    def extract(self, pkg_path: Path, target_dir: Path) -> ExtractResult:
        _log.info("Extracting Deb: %s", pkg_path)
        self._deb_extract(pkg_path, target_dir)
        return ExtractResult(lib_dir=target_dir)

    def _deb_extract(self, deb_path: Path, target_dir: Path) -> None:
        """Extract Debian package: ar x to get data.tar.*, then tar extract."""
        ar = shutil.which("ar")
        if not ar:
            raise RuntimeError(
                "ar not found. Install binutils or use a tar archive instead."
            )

        # ar extract into a staging area
        staging = Path(tempfile.mkdtemp(dir=target_dir, prefix=".deb_staging_"))
        try:
            subprocess.run(
                [ar, "x", str(deb_path)],
                cwd=str(staging),
                check=True,
                capture_output=True,
            )

            # Find data.tar.* member
            data_tar = None
            for candidate in staging.iterdir():
                if candidate.name.startswith("data.tar"):
                    data_tar = candidate
                    break

            if data_tar is None:
                raise RuntimeError(
                    f"No data.tar.* found in Deb package: {deb_path}"
                )

            # Extract data.tar.* with security checks
            TarExtractor._safe_extract(data_tar, target_dir)
        finally:
            shutil.rmtree(staging, ignore_errors=True)


# ── Zip-based security helper ────────────────────────────────────────────────


def _safe_zip_extract(archive_path: Path, target_dir: Path) -> None:
    """Extract a zip archive with full security validation on every member."""
    target_root = target_dir.resolve()
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            _validate_member_path(info.filename, target_root)
        zf.extractall(path=target_dir)


# ── Conda extractor ─────────────────────────────────────────────────────────


class CondaExtractor:
    """Extract conda packages (.conda v2 format and legacy .tar.bz2).

    .conda format is a zip archive containing:
      - metadata.json
      - pkg-<name>-<hash>.tar.zst  (package payload)
      - info-<name>-<hash>.tar.zst (metadata)

    Legacy .tar.bz2 conda packages are plain bzip2-compressed tarballs.
    """

    def detect(self, pkg_path: Path) -> bool:
        name = pkg_path.name.lower()
        if name.endswith(".conda"):
            return True
        # Legacy conda packages end with .tar.bz2 but we need to distinguish
        # from generic tar.bz2.  Check for conda-style naming:
        # <name>-<version>-<build>.tar.bz2
        if name.endswith(".tar.bz2") and name.count("-") >= 2:
            # Peek inside for info/ directory (conda marker)
            try:
                with tarfile.open(pkg_path, "r:bz2") as tf:
                    names = tf.getnames()
                    return any(n.startswith("info/") for n in names[:50])
            except (tarfile.TarError, OSError):
                return False
        return False

    def extract(self, pkg_path: Path, target_dir: Path) -> ExtractResult:
        _log.info("Extracting conda package: %s", pkg_path)
        name = pkg_path.name.lower()

        if name.endswith(".conda"):
            self._extract_v2(pkg_path, target_dir)
        else:
            # Legacy .tar.bz2 format
            TarExtractor._safe_extract(pkg_path, target_dir)

        return ExtractResult(lib_dir=target_dir)

    @staticmethod
    def _extract_v2(conda_path: Path, target_dir: Path) -> None:
        """Extract .conda v2 format (zip containing tar.zst payloads)."""
        target_root = target_dir.resolve()

        # First extract the outer zip
        staging = Path(tempfile.mkdtemp(dir=target_dir, prefix=".conda_staging_"))
        try:
            _safe_zip_extract(conda_path, staging)

            # Find and extract pkg-*.tar.zst (the main payload)
            for member in staging.iterdir():
                if member.name.startswith("pkg-") and member.name.endswith(".tar.zst"):
                    CondaExtractor._extract_zst_tar(member, target_dir)
                elif member.name.startswith("info-") and member.name.endswith(".tar.zst"):
                    # Also extract info for metadata
                    info_dir = target_dir / "info"
                    info_dir.mkdir(exist_ok=True)
                    CondaExtractor._extract_zst_tar(member, info_dir)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _extract_zst_tar(zst_path: Path, target_dir: Path) -> None:
        """Extract a .tar.zst file using zstd + tar or Python zstandard."""
        # Try Python zstandard first
        try:
            import zstandard
            dctx = zstandard.ZstdDecompressor()
            with open(zst_path, "rb") as compressed:
                with dctx.stream_reader(compressed) as reader:
                    with tarfile.open(fileobj=reader, mode="r|") as tf:
                        target_root = target_dir.resolve()
                        for member in tf:
                            _validate_member_path(member.name, target_root)
                            if member.issym() or member.islnk():
                                _validate_symlink_target(
                                    member.name, member.linkname, target_root
                                )
                        # Re-read for extraction (stream was consumed)
                with open(zst_path, "rb") as compressed2:
                    with dctx.stream_reader(compressed2) as reader2:
                        with tarfile.open(fileobj=reader2, mode="r|") as tf2:
                            if sys.version_info >= (3, 12):
                                tf2.extractall(path=target_dir, filter="data")
                            else:
                                tf2.extractall(path=target_dir)
            return
        except ImportError:
            pass

        # Fall back to system zstd command
        zstd = shutil.which("zstd")
        if zstd is None:
            raise RuntimeError(
                "Cannot extract .tar.zst: install 'zstandard' Python package "
                "or 'zstd' command-line tool."
            )
        # Decompress to tar, then extract
        tar_path = zst_path.with_suffix("")  # strip .zst
        subprocess.run(
            [zstd, "-d", str(zst_path), "-o", str(tar_path)],
            check=True,
            capture_output=True,
        )
        try:
            TarExtractor._safe_extract(tar_path, target_dir)
        finally:
            tar_path.unlink(missing_ok=True)


# ── Wheel (pip) extractor ────────────────────────────────────────────────────


class WheelExtractor:
    """Extract Python wheel (.whl) packages.

    Wheels are zip archives containing the package's files plus
    a .dist-info directory with metadata.
    """

    def detect(self, pkg_path: Path) -> bool:
        return pkg_path.name.lower().endswith(".whl")

    def extract(self, pkg_path: Path, target_dir: Path) -> ExtractResult:
        _log.info("Extracting wheel: %s", pkg_path)
        _safe_zip_extract(pkg_path, target_dir)
        return ExtractResult(lib_dir=target_dir)


# ── Directory passthrough ────────────────────────────────────────────────────


class DirExtractor:
    """Passthrough extractor for directories (no extraction needed)."""

    def detect(self, pkg_path: Path) -> bool:
        return pkg_path.is_dir()

    def extract(self, pkg_path: Path, target_dir: Path) -> ExtractResult:
        return ExtractResult(lib_dir=pkg_path)


# ── Auto-detection ───────────────────────────────────────────────────────────

_EXTRACTORS: list[PackageExtractor] = [
    DirExtractor(),
    CondaExtractor(),
    WheelExtractor(),
    TarExtractor(),
    RpmExtractor(),
    DebExtractor(),
]


def detect_extractor(path: Path) -> PackageExtractor | None:
    """Auto-detect package format and return the appropriate extractor.

    Returns None if the path is not a recognized package format.
    """
    for ext in _EXTRACTORS:
        if ext.detect(path):
            return ext
    return None


def is_package(path: Path) -> bool:
    """Return True if path is a recognized package format (not a plain directory)."""
    if path.is_dir():
        return False
    name = path.name.lower()
    if name.endswith((
        ".rpm", ".deb", ".tar", ".tar.gz", ".tar.xz", ".tar.bz2", ".tgz",
        ".conda", ".whl",
    )):
        return True
    # Check magic bytes for RPM / Deb
    try:
        with open(path, "rb") as f:
            magic = f.read(8)
        if magic[:4] == _RPM_MAGIC:
            return True
        if magic[:8] == _DEB_MAGIC:
            return True
    except OSError:
        pass
    return False


# ── Binary discovery ─────────────────────────────────────────────────────────

# ELF magic bytes
_ELF_MAGIC = b"\x7fELF"
# ELF type ET_DYN (shared object)
_ET_DYN = 3


def _is_elf_shared_object(path: Path) -> bool:
    """Check if a file is an ELF shared object (ET_DYN)."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != _ELF_MAGIC:
                return False
            # Skip EI_CLASS (byte 4) to determine endianness
            ei_class = struct.unpack("B", f.read(1))[0]
            ei_data = struct.unpack("B", f.read(1))[0]  # byte 5

            # Seek to e_type at offset 16
            f.seek(16)
            byte_order = "<" if ei_data == 1 else ">"
            e_type = struct.unpack(f"{byte_order}H", f.read(2))[0]
            return e_type == _ET_DYN
    except (OSError, struct.error):
        return False


def discover_shared_libraries(
    extract_dir: Path,
    *,
    include_private: bool = False,
) -> list[Path]:
    """Find all shared libraries in an extracted package directory.

    Walks the directory tree, identifies ELF shared objects (ET_DYN),
    and returns their paths sorted by name.

    Args:
        extract_dir: Root directory to search.
        include_private: If True, include DSOs from non-standard paths
            (e.g. private plugin directories).
    """
    _PUBLIC_LIB_DIRS = {"lib", "lib64", "usr/lib", "usr/lib64", "usr/local/lib", "usr/local/lib64"}

    libraries: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(extract_dir, followlinks=False):
        for fn in filenames:
            fp = Path(dirpath) / fn
            if fp.is_symlink():
                # Follow symlinks only to check the target, don't add symlinks themselves
                # unless the target is a real shared object
                try:
                    real = fp.resolve()
                    if not real.exists():
                        continue
                except OSError:
                    continue

            if not _is_elf_shared_object(fp):
                continue

            # Filter by path convention unless --include-private-dso
            if not include_private:
                try:
                    rel = fp.relative_to(extract_dir)
                except ValueError:
                    continue
                rel_parts = "/".join(rel.parts[:-1])
                # Check if it's in a known library directory
                in_public = any(
                    rel_parts == d or rel_parts.startswith(d + "/")
                    for d in _PUBLIC_LIB_DIRS
                )
                # Also accept files with .so in name at any depth as a fallback
                # for flat directory layouts (e.g. plain tar archives)
                name_lower = fn.lower()
                has_so_ext = ".so" in name_lower
                if not in_public and not has_so_ext:
                    continue

            libraries.append(fp)

    return sorted(libraries, key=lambda p: p.name)


# ── Debug info resolution ────────────────────────────────────────────────────


def resolve_debug_info(
    binary_path: Path,
    debug_dir: Path,
) -> Path | None:
    """Resolve debug info file for a binary from an extracted debug package.

    Tries two strategies:
    1. Build-id: read NT_GNU_BUILD_ID from binary, look up in .build-id dir
    2. Path convention: /usr/lib/debug/<binary-path>.debug
    """
    # Strategy 1: build-id
    build_id = _read_build_id(binary_path)
    if build_id:
        # build-id layout: .build-id/ab/cdef1234.debug
        bid_dir = build_id[:2]
        bid_file = build_id[2:] + ".debug"
        for search_root in [debug_dir, debug_dir / "usr" / "lib" / "debug"]:
            candidate = search_root / ".build-id" / bid_dir / bid_file
            if candidate.exists():
                _log.debug("Debug info resolved via build-id: %s", candidate)
                return candidate

    # Strategy 2: path convention
    # The binary at /usr/lib64/libfoo.so.1 has debug at
    # <debug_dir>/usr/lib/debug/usr/lib64/libfoo.so.1.debug
    name = binary_path.name
    for search_root in [debug_dir, debug_dir / "usr" / "lib" / "debug"]:
        for candidate in search_root.rglob(f"{name}.debug"):
            _log.debug("Debug info resolved via path convention: %s", candidate)
            return candidate

    return None


def _read_build_id(binary_path: Path) -> str | None:
    """Read GNU build-id from an ELF binary.

    Returns the build-id as a hex string, or None if not found.
    """
    try:
        from elftools.elf.elffile import ELFFile
        with open(binary_path, "rb") as f:
            elf = ELFFile(f)
            for section in elf.iter_sections():
                if section.name == ".note.gnu.build-id":
                    for note in section.iter_notes():
                        if note["n_type"] == "NT_GNU_BUILD_ID":
                            return note["n_desc"]
    except Exception:
        _log.debug("Failed to read build-id from %s", binary_path, exc_info=True)
    return None
