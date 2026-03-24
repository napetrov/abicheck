"""Tests for diffoscope bridge (4a)."""
from pathlib import Path
from unittest import mock

from abicheck.diffoscope_bridge import run_diffoscope


class TestRunDiffoscope:
    def test_returns_output_on_diff(self):
        result = mock.Mock(returncode=1, stdout="binary diff output\n", stderr="")
        with mock.patch("subprocess.run", return_value=result):
            output = run_diffoscope(Path("old.so"), Path("new.so"))
        assert output == "binary diff output\n"

    def test_returns_output_on_identical(self):
        result = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=result):
            output = run_diffoscope(Path("old.so"), Path("new.so"))
        assert output == ""

    def test_returns_none_on_not_found(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            output = run_diffoscope(Path("old.so"), Path("new.so"))
        assert output is None

    def test_returns_none_on_timeout(self):
        import subprocess
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="diffoscope", timeout=60)):
            output = run_diffoscope(Path("old.so"), Path("new.so"))
        assert output is None

    def test_returns_none_on_error_exit(self):
        result = mock.Mock(returncode=2, stdout="", stderr="some error")
        with mock.patch("subprocess.run", return_value=result):
            output = run_diffoscope(Path("old.so"), Path("new.so"))
        assert output is None

    def test_returns_none_on_os_error(self):
        with mock.patch("subprocess.run", side_effect=OSError("permission denied")):
            output = run_diffoscope(Path("old.so"), Path("new.so"))
        assert output is None

    def test_custom_timeout(self):
        result = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=result) as m:
            run_diffoscope(Path("old.so"), Path("new.so"), timeout=30)
        m.assert_called_once()
        assert m.call_args.kwargs.get("timeout") == 30 or m.call_args[1].get("timeout") == 30
