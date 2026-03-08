"""conftest.py — pytest configuration for abicheck tests."""
import shutil

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: requires castxml, gcc/g++ installed",
    )
    config.addinivalue_line(
        "markers",
        "abicc: requires abi-compliance-checker + gcc/g++ — ABICC parity tests",
    )


def pytest_collection_modifyitems(config, items):
    missing = [t for t in ("castxml", "gcc", "g++") if shutil.which(t) is None]
    if missing:
        reason = f"Required tools not found: {', '.join(missing)}"
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)

    if shutil.which("abi-compliance-checker") is None:
        skip_abicc = pytest.mark.skip(reason="abi-compliance-checker not found in PATH")
        for item in items:
            if "abicc" in item.keywords:
                item.add_marker(skip_abicc)
