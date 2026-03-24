"""Tests for naming collision clarity (6a-6c)."""
import subprocess
import sys


class TestMainModule:
    def test_python_m_abicheck_version(self):
        """python -m abicheck --version should work."""
        result = subprocess.run(
            [sys.executable, "-m", "abicheck", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "napetrov/abicheck" in result.stdout

    def test_version_output_format(self):
        """Version output should include project qualifier."""
        result = subprocess.run(
            [sys.executable, "-m", "abicheck", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        # Format: "abicheck X.Y.Z (napetrov/abicheck)"
        assert "(napetrov/abicheck)" in result.stdout
