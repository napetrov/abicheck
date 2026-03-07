"""conftest.py — pytest configuration for abicheck tests."""
import shutil
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: requires castxml, gcc/g++ installed",
    )


def pytest_collection_modifyitems(config, items):
    if shutil.which("castxml") is None:
        skip = pytest.mark.skip(reason="castxml not found in PATH; skipping integration tests")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)
