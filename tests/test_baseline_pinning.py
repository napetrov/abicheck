"""Tests for baseline pinning: provenance metadata (schema v4), output naming, upload."""
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import click
import pytest

from abicheck.model import AbiSnapshot
from abicheck.serialization import (
    SCHEMA_VERSION,
    load_snapshot,
    save_snapshot,
    snapshot_from_dict,
    snapshot_to_dict,
)


def _sample_snap(**kwargs) -> AbiSnapshot:
    defaults = dict(library="libfoo.so.1", version="2.0.0")
    defaults.update(kwargs)
    return AbiSnapshot(**defaults)


# ---------------------------------------------------------------------------
# 1a. Provenance metadata (schema v4)
# ---------------------------------------------------------------------------

class TestSchemaV4:
    def test_schema_version_is_4(self):
        assert SCHEMA_VERSION == 4

    def test_provenance_fields_roundtrip(self):
        snap = _sample_snap(
            git_commit="abc1234def5678",
            git_tag="v2.0.0",
            created_at="2026-03-24T12:00:00+00:00",
            build_id="ci-run-42",
        )
        d = snapshot_to_dict(snap)
        assert d["schema_version"] == 4
        assert d["git_commit"] == "abc1234def5678"
        assert d["git_tag"] == "v2.0.0"
        assert d["created_at"] == "2026-03-24T12:00:00+00:00"
        assert d["build_id"] == "ci-run-42"

        snap2 = snapshot_from_dict(d)
        assert snap2.git_commit == "abc1234def5678"
        assert snap2.git_tag == "v2.0.0"
        assert snap2.created_at == "2026-03-24T12:00:00+00:00"
        assert snap2.build_id == "ci-run-42"

    def test_provenance_fields_default_none(self):
        snap = _sample_snap()
        assert snap.git_commit is None
        assert snap.git_tag is None
        assert snap.created_at is None
        assert snap.build_id is None

    def test_v3_snapshot_loads_without_provenance(self):
        """Old v3 snapshots should load fine — provenance defaults to None."""
        d = {
            "schema_version": 3,
            "library": "libold.so",
            "version": "1.0",
        }
        snap = snapshot_from_dict(d)
        assert snap.library == "libold.so"
        assert snap.git_commit is None
        assert snap.git_tag is None
        assert snap.created_at is None
        assert snap.build_id is None

    def test_provenance_file_roundtrip(self):
        snap = _sample_snap(
            git_commit="deadbeef",
            git_tag="v2.0.0",
            created_at="2026-03-24T00:00:00+00:00",
            build_id="gh-actions-1234",
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)
        try:
            save_snapshot(snap, tmp)
            # Verify JSON on disk has provenance
            raw = json.loads(tmp.read_text())
            assert raw["git_commit"] == "deadbeef"
            assert raw["schema_version"] == 4

            snap2 = load_snapshot(tmp)
            assert snap2.git_commit == "deadbeef"
            assert snap2.build_id == "gh-actions-1234"
        finally:
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 1b. Output naming (_resolve_output)
# ---------------------------------------------------------------------------

class TestResolveOutput:
    def test_explicit_output_wins(self):
        from abicheck.cli import _resolve_output
        snap = _sample_snap()
        assert _resolve_output(Path("my.json"), None, snap) == Path("my.json")

    def test_output_name_auto_so(self):
        from abicheck.cli import _resolve_output
        snap = _sample_snap(library="libfoo.so.1", version="2.0.0")
        result = _resolve_output(None, "auto", snap)
        assert result == Path("libfoo-2.0.0.abicheck.json")

    def test_output_name_auto_so_multi_version(self):
        from abicheck.cli import _resolve_output
        snap = _sample_snap(library="libfoo.so.1.2.3", version="2.0.0")
        result = _resolve_output(None, "auto", snap)
        assert result == Path("libfoo-2.0.0.abicheck.json")

    def test_output_name_auto_dll(self):
        from abicheck.cli import _resolve_output
        snap = _sample_snap(library="foo.dll", version="3.1")
        result = _resolve_output(None, "auto", snap)
        assert result == Path("foo-3.1.abicheck.json")

    def test_output_name_auto_dylib(self):
        from abicheck.cli import _resolve_output
        snap = _sample_snap(library="libbar.dylib", version="1.0")
        result = _resolve_output(None, "auto", snap)
        assert result == Path("libbar-1.0.abicheck.json")

    def test_output_name_auto_unknown_version(self):
        from abicheck.cli import _resolve_output
        snap = _sample_snap(library="libfoo.so.1", version="unknown")
        result = _resolve_output(None, "auto", snap)
        assert result == Path("libfoo.abicheck.json")

    def test_no_output_returns_none(self):
        from abicheck.cli import _resolve_output
        snap = _sample_snap()
        assert _resolve_output(None, None, snap) is None

    def test_output_name_auto_empty_library_raises(self):
        from abicheck.cli import _resolve_output
        snap = _sample_snap(library="")
        with pytest.raises(click.ClickException, match="empty"):
            _resolve_output(None, "auto", snap)


# ---------------------------------------------------------------------------
# Provenance stamping (_stamp_provenance)
# ---------------------------------------------------------------------------

class TestStampProvenance:
    def test_stamp_sets_created_at(self):
        from abicheck.cli import _stamp_provenance
        snap = _sample_snap()
        _stamp_provenance(snap, git_tag=None, build_id=None, no_git=True)
        assert snap.created_at is not None
        # Verify ISO 8601 format
        assert "T" in snap.created_at

    def test_stamp_sets_git_tag_and_build_id(self):
        from abicheck.cli import _stamp_provenance
        snap = _sample_snap()
        _stamp_provenance(snap, git_tag="v1.0", build_id="run-99", no_git=True)
        assert snap.git_tag == "v1.0"
        assert snap.build_id == "run-99"

    def test_stamp_auto_detects_git_commit(self):
        from abicheck.cli import _stamp_provenance
        snap = _sample_snap()
        fake_result = mock.Mock(returncode=0, stdout="abc1234\n", stderr="")
        with mock.patch("subprocess.run", return_value=fake_result) as m:
            _stamp_provenance(snap, git_tag=None, build_id=None, no_git=False)
        assert snap.git_commit == "abc1234"
        m.assert_called_once_with(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )

    def test_stamp_no_git_skips_detection(self):
        from abicheck.cli import _stamp_provenance
        snap = _sample_snap()
        with mock.patch("subprocess.run") as m:
            _stamp_provenance(snap, git_tag=None, build_id=None, no_git=True)
        m.assert_not_called()
        assert snap.git_commit is None

    def test_stamp_git_not_found_graceful(self):
        from abicheck.cli import _stamp_provenance
        snap = _sample_snap()
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            _stamp_provenance(snap, git_tag=None, build_id=None, no_git=False)
        assert snap.git_commit is None

    def test_stamp_git_timeout_graceful(self):
        from abicheck.cli import _stamp_provenance
        snap = _sample_snap()
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5)):
            _stamp_provenance(snap, git_tag=None, build_id=None, no_git=False)
        assert snap.git_commit is None


# ---------------------------------------------------------------------------
# 1d. Upload release (_upload_to_release)
# ---------------------------------------------------------------------------

class TestUploadToRelease:
    def test_upload_calls_gh(self, tmp_path):
        from abicheck.cli import _upload_to_release
        snap = tmp_path / "snap.json"
        snap.write_text("{}")
        with mock.patch("subprocess.run") as m:
            m.return_value = mock.Mock(returncode=0)
            _upload_to_release(snap, "v2.0.0")
        m.assert_called_once_with(
            ["gh", "release", "upload", "--clobber", "--", "v2.0.0", str(snap.resolve())],
            check=True, timeout=60,
        )

    def test_upload_auto_detects_tag(self, tmp_path):
        from abicheck.cli import _upload_to_release
        snap = tmp_path / "snap.json"
        snap.write_text("{}")
        tag_result = mock.Mock(returncode=0, stdout="v1.0.0\n", stderr="")
        upload_result = mock.Mock(returncode=0)
        with mock.patch("subprocess.run", side_effect=[tag_result, upload_result]) as m:
            _upload_to_release(snap, None)
        # First call: git describe, second: gh release upload
        assert m.call_count == 2

    def test_upload_no_tag_raises(self, tmp_path):
        from abicheck.cli import _upload_to_release
        snap = tmp_path / "snap.json"
        snap.write_text("{}")
        tag_result = mock.Mock(returncode=1, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=tag_result):
            with pytest.raises(click.ClickException, match="could not determine release tag"):
                _upload_to_release(snap, None)

    def test_upload_gh_not_found_raises(self, tmp_path):
        from abicheck.cli import _upload_to_release
        snap = tmp_path / "snap.json"
        snap.write_text("{}")
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(click.ClickException, match="GitHub CLI"):
                _upload_to_release(snap, "v1.0")

    def test_upload_called_process_error_raises(self, tmp_path):
        from abicheck.cli import _upload_to_release
        snap = tmp_path / "snap.json"
        snap.write_text("{}")
        with mock.patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "gh")):
            with pytest.raises(click.ClickException, match="Failed to upload"):
                _upload_to_release(snap, "v1.0")

    def test_upload_timeout_raises(self, tmp_path):
        from abicheck.cli import _upload_to_release
        snap = tmp_path / "snap.json"
        snap.write_text("{}")
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=60)):
            with pytest.raises(click.ClickException, match="timed out"):
                _upload_to_release(snap, "v1.0")
