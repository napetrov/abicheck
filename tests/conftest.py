"""conftest.py — pytest configuration for abicheck tests."""
import shutil
import sys

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
        "integration: requires platform-specific compiler (gcc/g++ on Linux, clang on macOS, MinGW gcc on Windows)",
    )
    config.addinivalue_line(
        "markers",
        "abicc: requires abi-compliance-checker + gcc/g++ — ABICC parity tests",
    )
    config.addinivalue_line(
        "markers",
        "golden: golden-output regression test (use --update-goldens to refresh)",
    )


def _integration_skip_reason() -> str | None:
    """Return a skip reason if integration tests cannot run, or None if they can.

    Platform-specific requirements:
    - Linux: castxml + gcc + g++ (ELF integration tests)
    - macOS: clang (Mach-O integration tests; ships with Xcode CLT)
    - Windows: gcc from MinGW (PE/DLL integration tests)
    """
    if sys.platform == "darwin":
        if shutil.which("clang") is None:
            return "clang not found in PATH (required for macOS integration tests)"
        return None

    if sys.platform == "win32":
        if shutil.which("gcc") is None:
            return "gcc (MinGW) not found in PATH (required for Windows integration tests)"
        return None

    # Linux / other Unix: require castxml + gcc + g++ for ELF tests
    missing = [t for t in ("castxml", "gcc", "g++") if shutil.which(t) is None]
    if missing:
        return f"Required tools not found: {', '.join(missing)}"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    reason = _integration_skip_reason()
    if reason:
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
