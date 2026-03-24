"""Tests for snapshot schema backward/forward compatibility (3a-3d).

Golden fixtures in tests/fixtures/schema/ represent each schema version with
identical logical content. Tests verify:
- Every version loads successfully
- Self-comparison produces NO_CHANGE
- Cross-version comparison produces NO_CHANGE
- Reserialization always writes current schema version
"""
import json
import warnings
from pathlib import Path

import pytest

from abicheck.checker import Verdict, compare
from abicheck.serialization import (
    SCHEMA_VERSION,
    snapshot_from_dict,
    snapshot_to_dict,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "schema"

# All fixture files, parameterized
SCHEMA_VERSIONS = [
    pytest.param("v1.json", id="v1-no-schema-version"),
    pytest.param("v2.json", id="v2"),
    pytest.param("v3.json", id="v3"),
    pytest.param("v4.json", id="v4-provenance"),
]


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


# ---------------------------------------------------------------------------
# 3b. Parameterized load tests
# ---------------------------------------------------------------------------

class TestLoadAllVersions:
    @pytest.mark.parametrize("fixture", SCHEMA_VERSIONS)
    def test_loads_successfully(self, fixture):
        d = _load_fixture(fixture)
        snap = snapshot_from_dict(d)
        assert snap.library == "libcompat.so.1"
        assert snap.version == "1.0.0"
        assert len(snap.functions) == 2
        assert len(snap.types) == 1
        assert len(snap.enums) == 1

    @pytest.mark.parametrize("fixture", SCHEMA_VERSIONS)
    def test_self_compare_no_change(self, fixture):
        d = _load_fixture(fixture)
        snap = snapshot_from_dict(d)
        result = compare(snap, snap)
        assert result.verdict == Verdict.NO_CHANGE

    @pytest.mark.parametrize("fixture", SCHEMA_VERSIONS)
    def test_functions_correct(self, fixture):
        d = _load_fixture(fixture)
        snap = snapshot_from_dict(d)
        names = {f.name for f in snap.functions}
        assert names == {"compat_init", "compat_free"}

    @pytest.mark.parametrize("fixture", SCHEMA_VERSIONS)
    def test_types_correct(self, fixture):
        d = _load_fixture(fixture)
        snap = snapshot_from_dict(d)
        assert snap.types[0].name == "compat_config"
        assert len(snap.types[0].fields) == 2

    @pytest.mark.parametrize("fixture", SCHEMA_VERSIONS)
    def test_enums_correct(self, fixture):
        d = _load_fixture(fixture)
        snap = snapshot_from_dict(d)
        assert snap.enums[0].name == "compat_status"
        assert len(snap.enums[0].members) == 2


# ---------------------------------------------------------------------------
# 3c. Cross-version comparison tests
# ---------------------------------------------------------------------------

class TestCrossVersionCompare:
    def test_v1_vs_v3_no_change(self):
        """Same content in v1 and v3 format — compare must produce NO_CHANGE."""
        snap_v1 = snapshot_from_dict(_load_fixture("v1.json"))
        snap_v3 = snapshot_from_dict(_load_fixture("v3.json"))
        result = compare(snap_v1, snap_v3)
        assert result.verdict == Verdict.NO_CHANGE

    def test_v1_vs_v4_no_change(self):
        """v4 has extra provenance fields but same ABI content."""
        snap_v1 = snapshot_from_dict(_load_fixture("v1.json"))
        snap_v4 = snapshot_from_dict(_load_fixture("v4.json"))
        result = compare(snap_v1, snap_v4)
        assert result.verdict == Verdict.NO_CHANGE

    def test_v2_vs_v4_no_change(self):
        snap_v2 = snapshot_from_dict(_load_fixture("v2.json"))
        snap_v4 = snapshot_from_dict(_load_fixture("v4.json"))
        result = compare(snap_v2, snap_v4)
        assert result.verdict == Verdict.NO_CHANGE

    def test_v3_vs_v4_no_change(self):
        snap_v3 = snapshot_from_dict(_load_fixture("v3.json"))
        snap_v4 = snapshot_from_dict(_load_fixture("v4.json"))
        result = compare(snap_v3, snap_v4)
        assert result.verdict == Verdict.NO_CHANGE


# ---------------------------------------------------------------------------
# 3d. Reserialization stability tests
# ---------------------------------------------------------------------------

class TestReserialization:
    @pytest.mark.parametrize("fixture", SCHEMA_VERSIONS)
    def test_reserialized_to_current_version(self, fixture):
        """Loading any version and re-serializing should produce current schema_version."""
        d = _load_fixture(fixture)
        snap = snapshot_from_dict(d)
        reserialized = snapshot_to_dict(snap)
        assert reserialized["schema_version"] == SCHEMA_VERSION

    def test_v1_roundtrip_no_data_loss(self):
        """Load v1 → serialize → reload: all ABI content preserved."""
        d = _load_fixture("v1.json")
        snap = snapshot_from_dict(d)
        reserialized = snapshot_to_dict(snap)
        snap2 = snapshot_from_dict(reserialized)
        assert len(snap2.functions) == len(snap.functions)
        assert len(snap2.types) == len(snap.types)
        assert len(snap2.enums) == len(snap.enums)
        assert snap2.library == snap.library
        assert snap2.version == snap.version

    def test_v4_provenance_preserved(self):
        """v4 provenance fields survive roundtrip."""
        d = _load_fixture("v4.json")
        snap = snapshot_from_dict(d)
        assert snap.git_commit == "abc1234"
        assert snap.git_tag == "v1.0.0"
        reserialized = snapshot_to_dict(snap)
        assert reserialized["git_commit"] == "abc1234"
        assert reserialized["git_tag"] == "v1.0.0"

    def test_future_version_warning(self):
        """Loading a snapshot with schema_version > current emits a warning."""
        d = _load_fixture("v4.json")
        d["schema_version"] = 999
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            snap = snapshot_from_dict(d)
            assert len(w) == 1
            assert "newer than this abicheck" in str(w[0].message)
        # But still loads successfully
        assert snap.library == "libcompat.so.1"
