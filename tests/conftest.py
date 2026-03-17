"""conftest.py — pytest configuration for abicheck tests."""
import shutil
import subprocess
import sys
from pathlib import Path

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


@pytest.fixture(scope="session")
def shared_cmake_build_dir(tmp_path_factory: pytest.TempPathFactory) -> Path | None:
    """Session-scoped CMake build directory for integration tests.

    Configures the examples/ CMakeLists.txt **once** per session so that
    individual tests only need to run ``cmake --build`` for their specific
    targets.  On Windows this avoids ~30 redundant cmake-configure passes
    (each one re-parses all 63 example CMakeLists).
    """
    examples_dir = Path(__file__).parent.parent / "examples"
    cmake_lists = examples_dir / "CMakeLists.txt"
    cmake = shutil.which("cmake")

    if not cmake or not cmake_lists.exists():
        return None

    build_dir = tmp_path_factory.mktemp("cmake_build")
    r = subprocess.run(
        [cmake, "-S", str(examples_dir), "-B", str(build_dir),
         "-DCMAKE_BUILD_TYPE=Debug"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        return None

    return build_dir
