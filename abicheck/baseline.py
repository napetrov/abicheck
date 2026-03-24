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

"""Baseline Registry — store and retrieve ABI baseline snapshots (ADR-022).

Provides a pluggable registry for ABI baseline management with multiple
backends:

- **Filesystem** (default): Plain directory structure on local/network FS
- **Git-native** (future): Dedicated branch in the repository
- **OCI** (future): OCI artifacts via ORAS conventions

Usage::

    from abicheck.baseline import BaselineKey, BaselineMetadata, FilesystemRegistry

    registry = FilesystemRegistry(Path("/shared/abi-baselines"))
    key = BaselineKey(library="libfoo", version="1.0.0", platform="linux-x86_64")

    # Push a baseline
    registry.push(key, snapshot, metadata)

    # Pull a baseline
    result = registry.pull(key)
    if result:
        snapshot, metadata = result

    # List baselines
    for key in registry.list():
        print(key.path)
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from . import __version__ as _abicheck_version
from .model import AbiSnapshot
from .serialization import load_snapshot, snapshot_to_json

_logger = logging.getLogger(__name__)

# Current baseline metadata schema version
_METADATA_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BaselineKey:
    """Unique identifier for a baseline snapshot (ADR-022)."""

    library: str
    version: str
    platform: str
    variant: str = ""

    @property
    def path(self) -> str:
        """Registry path: library/version/platform[/variant]."""
        parts = [self.library, self.version, self.platform]
        if self.variant:
            parts.append(self.variant)
        return "/".join(parts)

    @classmethod
    def from_path(cls, path: str) -> BaselineKey:
        """Parse a registry path into a BaselineKey.

        Accepts ``library/version/platform`` or
        ``library/version/platform/variant``.
        """
        parts = path.strip("/").split("/")
        if len(parts) < 3:
            raise ValueError(
                f"Invalid baseline path {path!r}: expected "
                "library/version/platform[/variant]"
            )
        return cls(
            library=parts[0],
            version=parts[1],
            platform=parts[2],
            variant=parts[3] if len(parts) > 3 else "",
        )

    @classmethod
    def from_spec(cls, spec: str) -> BaselineKey:
        """Parse a colon-separated spec into a BaselineKey.

        Accepts ``library:version:platform`` or
        ``library:version:platform:variant``.
        """
        parts = spec.split(":")
        if len(parts) < 3:
            raise ValueError(
                f"Invalid baseline spec {spec!r}: expected "
                "library:version:platform[:variant]"
            )
        return cls(
            library=parts[0],
            version=parts[1],
            platform=parts[2],
            variant=parts[3] if len(parts) > 3 else "",
        )

    def __str__(self) -> str:
        return self.path


@dataclass
class BaselineMetadata:
    """Provenance and integrity metadata for a baseline (ADR-022)."""

    abicheck_version: str = ""
    schema_version: int = _METADATA_SCHEMA_VERSION
    created_at: str = ""
    build_context_hash: str | None = None
    git_commit: str | None = None
    checksum: str = ""
    signature: str | None = None

    @classmethod
    def create(
        cls,
        snapshot_json: str,
        *,
        build_context_hash: str | None = None,
        git_commit: str | None = None,
    ) -> BaselineMetadata:
        """Create metadata for a new baseline with computed checksum."""
        return cls(
            abicheck_version=_abicheck_version,
            schema_version=_METADATA_SCHEMA_VERSION,
            created_at=datetime.now(timezone.utc).isoformat(),
            build_context_hash=build_context_hash,
            git_commit=git_commit,
            checksum=hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest(),
        )

    def verify_checksum(self, snapshot_json: str) -> bool:
        """Verify that the snapshot matches the stored checksum."""
        if not self.checksum:
            return True
        return hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest() == self.checksum

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> BaselineMetadata:
        return cls(
            abicheck_version=str(data.get("abicheck_version", "")),
            schema_version=int(data.get("schema_version", _METADATA_SCHEMA_VERSION)),
            created_at=str(data.get("created_at", "")),
            build_context_hash=data.get("build_context_hash"),  # type: ignore[arg-type]
            git_commit=data.get("git_commit"),  # type: ignore[arg-type]
            checksum=str(data.get("checksum", "")),
            signature=data.get("signature"),  # type: ignore[arg-type]
        )


class BaselineRegistry(Protocol):
    """Protocol for baseline storage backends (ADR-022)."""

    def push(
        self,
        key: BaselineKey,
        snapshot: AbiSnapshot,
        metadata: BaselineMetadata | None = None,
    ) -> str:
        """Store a baseline snapshot. Returns a reference ID."""
        ...

    def pull(self, key: BaselineKey) -> tuple[AbiSnapshot, BaselineMetadata] | None:
        """Retrieve a baseline by key. Returns None if not found."""
        ...

    def list(self, prefix: str | None = None) -> list[BaselineKey]:
        """List available baselines, optionally filtered by prefix."""
        ...

    def delete(self, key: BaselineKey) -> bool:
        """Delete a baseline. Returns True if deleted."""
        ...


class FilesystemRegistry:
    """Filesystem-based baseline registry (ADR-022).

    Stores baselines as plain files in a directory tree::

        <root>/
        ├── libfoo/
        │   ├── 1.0.0/
        │   │   └── linux-x86_64/
        │   │       ├── snapshot.json
        │   │       └── metadata.json
        │   └── main/
        │       └── linux-x86_64/
        │           ├── snapshot.json
        │           └── metadata.json
        └── libbar/
            └── 2.0.0/
                └── linux-x86_64/
                    ├── snapshot.json
                    └── metadata.json
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _key_dir(self, key: BaselineKey) -> Path:
        parts = [key.library, key.version, key.platform]
        if key.variant:
            parts.append(key.variant)
        return self._root / Path(*parts)

    def push(
        self,
        key: BaselineKey,
        snapshot: AbiSnapshot,
        metadata: BaselineMetadata | None = None,
    ) -> str:
        """Store a baseline snapshot to the filesystem."""
        key_dir = self._key_dir(key)
        key_dir.mkdir(parents=True, exist_ok=True)

        snap_json = snapshot_to_json(snapshot)

        if metadata is None:
            metadata = BaselineMetadata.create(snap_json)

        snap_path = key_dir / "snapshot.json"
        meta_path = key_dir / "metadata.json"

        snap_path.write_text(snap_json, encoding="utf-8")
        meta_path.write_text(
            json.dumps(metadata.to_dict(), indent=2),
            encoding="utf-8",
        )

        ref = f"fs://{key.path}"
        _logger.info("Baseline pushed: %s → %s", ref, key_dir)
        return ref

    def pull(self, key: BaselineKey) -> tuple[AbiSnapshot, BaselineMetadata] | None:
        """Retrieve a baseline snapshot from the filesystem."""
        key_dir = self._key_dir(key)
        snap_path = key_dir / "snapshot.json"
        meta_path = key_dir / "metadata.json"

        if not snap_path.exists():
            _logger.debug("Baseline not found: %s", key.path)
            return None

        # Load metadata
        meta = BaselineMetadata()
        if meta_path.exists():
            try:
                meta_raw = json.loads(meta_path.read_text(encoding="utf-8"))
                meta = BaselineMetadata.from_dict(meta_raw)
            except (json.JSONDecodeError, KeyError) as exc:
                _logger.warning("Invalid metadata for %s: %s", key.path, exc)

        # Load and verify snapshot
        snap_json = snap_path.read_text(encoding="utf-8")
        if not meta.verify_checksum(snap_json):
            _logger.warning(
                "Checksum mismatch for baseline %s — snapshot may have been "
                "modified since it was pushed",
                key.path,
            )

        snapshot = load_snapshot(snap_path)
        _logger.info("Baseline pulled: %s", key.path)
        return snapshot, meta

    def list(self, prefix: str | None = None) -> list[BaselineKey]:
        """List available baselines in the filesystem registry."""
        if not self._root.exists():
            return []

        keys: list[BaselineKey] = []
        for lib_dir in sorted(self._root.iterdir()):
            if not lib_dir.is_dir():
                continue
            library = lib_dir.name
            if prefix and not library.startswith(prefix):
                continue
            for ver_dir in sorted(lib_dir.iterdir()):
                if not ver_dir.is_dir():
                    continue
                version = ver_dir.name
                for plat_dir in sorted(ver_dir.iterdir()):
                    if not plat_dir.is_dir():
                        continue
                    platform = plat_dir.name
                    snap = plat_dir / "snapshot.json"
                    if snap.exists():
                        keys.append(BaselineKey(
                            library=library,
                            version=version,
                            platform=platform,
                        ))
                    # Also check for variant subdirectories
                    for var_dir in sorted(plat_dir.iterdir()):
                        if var_dir.is_dir() and (var_dir / "snapshot.json").exists():
                            keys.append(BaselineKey(
                                library=library,
                                version=version,
                                platform=platform,
                                variant=var_dir.name,
                            ))
        return keys

    def delete(self, key: BaselineKey) -> bool:
        """Delete a baseline from the filesystem registry."""
        key_dir = self._key_dir(key)
        snap_path = key_dir / "snapshot.json"
        if not snap_path.exists():
            return False

        import shutil
        shutil.rmtree(key_dir)

        # Clean up empty parent directories
        for parent in [key_dir.parent, key_dir.parent.parent]:
            try:
                if parent.exists() and parent != self._root and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass

        _logger.info("Baseline deleted: %s", key.path)
        return True


def detect_platform_from_binary(binary_path: Path) -> str:
    """Detect platform string from a binary file.

    Returns a string like "linux-x86_64", "windows-x86_64", "macos-arm64".
    """
    import sys

    from .binary_utils import detect_binary_format

    fmt = detect_binary_format(binary_path)
    if fmt is None:
        return f"{sys.platform}-unknown"

    arch = "unknown"
    if fmt == "elf":
        try:
            from elftools.elf.elffile import ELFFile
            with open(binary_path, "rb") as f:
                elf = ELFFile(f)  # type: ignore[no-untyped-call]
                machine = elf.header.e_machine
                arch_map = {
                    "EM_X86_64": "x86_64",
                    "EM_386": "x86",
                    "EM_AARCH64": "aarch64",
                    "EM_ARM": "arm",
                    "EM_RISCV": "riscv64",
                    "EM_PPC64": "ppc64",
                    "EM_S390": "s390x",
                }
                arch = arch_map.get(machine, str(machine))
        except Exception:  # noqa: BLE001
            pass
        return f"linux-{arch}"

    if fmt == "pe":
        try:
            import pefile
            pe = pefile.PE(str(binary_path), fast_load=True)
            machine = pe.FILE_HEADER.Machine
            if machine == 0x8664:
                arch = "x86_64"
            elif machine == 0x14C:
                arch = "x86"
            elif machine == 0xAA64:
                arch = "aarch64"
            pe.close()
        except Exception:  # noqa: BLE001
            pass
        return f"windows-{arch}"

    if fmt == "macho":
        return f"macos-{arch}"

    return f"unknown-{arch}"
