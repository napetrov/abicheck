"""conftest.py — pytest configuration for abicheck tests."""
import shutil

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register --update-goldens CLI option for golden-output tests."""
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Re-generate golden output files in tests/golden/ instead of comparing.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires castxml, gcc/g++ installed",
    )
    config.addinivalue_line(
        "markers",
        "abicc: requires abi-compliance-checker + gcc/g++ — ABICC parity tests",
    )
    config.addinivalue_line(
        "markers",
        "golden: golden-output regression test (use --update-goldens to refresh)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
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


@pytest.fixture
def update_goldens(request: pytest.FixtureRequest) -> bool:
    """True when --update-goldens flag is passed."""
    return bool(request.config.getoption("--update-goldens"))
