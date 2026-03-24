"""Tests for MCP auth hardening: file size limits, audit logging (2c, 2d)."""
import json
import logging
from pathlib import Path
from unittest import mock

import pytest

try:
    import abicheck.mcp_server as ms
    _has_mcp = True
except ImportError:
    _has_mcp = False

pytestmark = pytest.mark.skipif(not _has_mcp, reason="MCP dependencies not installed")


class TestCheckFileSize:
    def test_small_file_passes(self, tmp_path):
        p = tmp_path / "small.so"
        p.write_bytes(b"x" * 100)
        ms._check_file_size(p)  # should not raise

    def test_large_file_raises(self, tmp_path):
        old_limit = ms.MCP_MAX_FILE_SIZE
        try:
            ms.MCP_MAX_FILE_SIZE = 50  # 50 bytes
            p = tmp_path / "big.so"
            p.write_bytes(b"x" * 100)
            with pytest.raises(ValueError, match="exceeds limit"):
                ms._check_file_size(p)
        finally:
            ms.MCP_MAX_FILE_SIZE = old_limit

    def test_missing_file_no_error(self, tmp_path):
        ms._check_file_size(tmp_path / "nonexistent.so")  # should not raise


class TestAuditLog:
    def test_text_format(self, caplog):
        with caplog.at_level(logging.INFO, logger="abicheck.mcp"):
            ms._audit_log("abi_dump", {"library": "foo.so"}, 1.234, "ok")
        assert "tool=abi_dump" in caplog.text
        assert "duration=1.234s" in caplog.text
        assert "status=ok" in caplog.text

    def test_json_format(self, caplog):
        old = ms._structured_logging
        try:
            ms._structured_logging = True
            with caplog.at_level(logging.INFO, logger="abicheck.mcp"):
                ms._audit_log("abi_compare", {"old": "a.so", "new": "b.so"}, 2.5, "ok", verdict="NO_CHANGE")
            record = json.loads(caplog.text.strip())
            assert record["tool"] == "abi_compare"
            assert record["verdict"] == "NO_CHANGE"
        finally:
            ms._structured_logging = old

    def test_verdict_included_when_present(self, caplog):
        with caplog.at_level(logging.INFO, logger="abicheck.mcp"):
            ms._audit_log("abi_compare", {"old": "a.so"}, 1.0, "ok", verdict="BREAKING")
        assert "verdict=BREAKING" in caplog.text
