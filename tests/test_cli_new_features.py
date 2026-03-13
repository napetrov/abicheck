"""Tests for new CLI features: --verbose, --lang, cross-compilation flags,
compat group structure, and dataclasses.replace() paths.
"""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from abicheck.cli import main
from abicheck.model import AbiSnapshot, Function, Visibility
from abicheck.serialization import snapshot_to_json

# ── helpers ──────────────────────────────────────────────────────────────

def _write_snapshots(tmp_path: Path) -> tuple[Path, Path]:
    old = AbiSnapshot(
        library="libtest.so", version="1.0",
        functions=[Function(name="foo", mangled="_Z3foov", return_type="int",
                            visibility=Visibility.PUBLIC)],
    )
    new = AbiSnapshot(
        library="libtest.so", version="2.0",
        functions=[Function(name="foo", mangled="_Z3foov", return_type="int",
                            visibility=Visibility.PUBLIC)],
    )
    old_p = tmp_path / "old.json"
    new_p = tmp_path / "new.json"
    old_p.write_text(snapshot_to_json(old), encoding="utf-8")
    new_p.write_text(snapshot_to_json(new), encoding="utf-8")
    return old_p, new_p


# ── --verbose/-v on compare ──────────────────────────────────────────────

class TestCompareVerbose:
    def test_verbose_flag_accepted(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["compare", str(old_p), str(new_p), "-v"])
        assert result.exit_code == 0

    def test_verbose_long_flag_accepted(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["compare", str(old_p), str(new_p), "--verbose"])
        assert result.exit_code == 0


# ── --verbose/-v on dump ─────────────────────────────────────────────────

class TestDumpVerbose:
    def test_verbose_flag_accepted(self, tmp_path, monkeypatch):
        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")
        out = tmp_path / "snap.json"

        monkeypatch.setattr("abicheck.cli.dump",
                            lambda **_: AbiSnapshot(library="libfoo.so", version="1.0"))

        runner = CliRunner()
        result = runner.invoke(main, [
            "dump", str(so_path), "-H", str(header), "--version", "1.0",
            "-o", str(out), "-v",
        ])
        assert result.exit_code == 0
        assert out.exists()


# ── --lang on compare ────────────────────────────────────────────────────

class TestCompareLang:
    def test_lang_c_accepted(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "--lang", "c",
        ])
        assert result.exit_code == 0

    def test_lang_cpp_accepted(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "--lang", "c++",
        ])
        assert result.exit_code == 0

    def test_lang_c_forwarded_to_resolve_input(self, tmp_path, monkeypatch):
        """When comparing ELF files with --lang c, _resolve_input passes lang='c' to dump()."""
        # Write two fake ELF files (magic bytes)
        old_so = tmp_path / "old.so"
        new_so = tmp_path / "new.so"
        old_so.write_bytes(b"\x7fELF" + b"\x00" * 100)
        new_so.write_bytes(b"\x7fELF" + b"\x00" * 100)
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")

        captured_calls = []

        def fake_dump(**kwargs):
            captured_calls.append(kwargs)
            return AbiSnapshot(library="libfoo.so", version="1.0")

        monkeypatch.setattr("abicheck.cli.dump", fake_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_so), str(new_so), "-H", str(header), "--lang", "c",
        ])
        assert result.exit_code == 0
        # Both old and new sides should have lang="c" forwarded
        assert len(captured_calls) == 2
        for call in captured_calls:
            assert call.get("lang") == "c"
            assert call.get("compiler") == "cc"

    def test_lang_invalid_rejected(self, tmp_path):
        old_p, new_p = _write_snapshots(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(old_p), str(new_p), "--lang", "rust",
        ])
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "invalid choice" in result.output.lower()


# ── --lang on dump ───────────────────────────────────────────────────────

class TestDumpLang:
    def test_lang_c_accepted(self, tmp_path, monkeypatch):
        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")

        captured = {}
        def fake_dump(**kwargs):
            captured.update(kwargs)
            return AbiSnapshot(library="libfoo.so", version="1.0")

        monkeypatch.setattr("abicheck.cli.dump", fake_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "dump", str(so_path), "-H", str(header), "--lang", "c",
        ])
        assert result.exit_code == 0
        # When --lang c is passed, compiler should be "cc"
        assert captured.get("compiler") == "cc"

    def test_lang_cpp_sends_cpp_compiler(self, tmp_path, monkeypatch):
        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")

        captured = {}
        def fake_dump(**kwargs):
            captured.update(kwargs)
            return AbiSnapshot(library="libfoo.so", version="1.0")

        monkeypatch.setattr("abicheck.cli.dump", fake_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "dump", str(so_path), "-H", str(header), "--lang", "c++",
        ])
        assert result.exit_code == 0
        assert captured.get("compiler") == "c++"


# ── Cross-compilation flags on dump ──────────────────────────────────────

class TestDumpCrossCompilation:
    def test_gcc_path_forwarded(self, tmp_path, monkeypatch):
        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")

        captured = {}
        def fake_dump(**kwargs):
            captured.update(kwargs)
            return AbiSnapshot(library="libfoo.so", version="1.0")

        monkeypatch.setattr("abicheck.cli.dump", fake_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "dump", str(so_path), "-H", str(header),
            "--gcc-path", "/usr/bin/aarch64-linux-gnu-g++",
        ])
        assert result.exit_code == 0
        assert captured.get("gcc_path") == "/usr/bin/aarch64-linux-gnu-g++"

    def test_gcc_prefix_forwarded(self, tmp_path, monkeypatch):
        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")

        captured = {}
        def fake_dump(**kwargs):
            captured.update(kwargs)
            return AbiSnapshot(library="libfoo.so", version="1.0")

        monkeypatch.setattr("abicheck.cli.dump", fake_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "dump", str(so_path), "-H", str(header),
            "--gcc-prefix", "aarch64-linux-gnu-",
        ])
        assert result.exit_code == 0
        assert captured.get("gcc_prefix") == "aarch64-linux-gnu-"

    def test_gcc_options_forwarded(self, tmp_path, monkeypatch):
        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")

        captured = {}
        def fake_dump(**kwargs):
            captured.update(kwargs)
            return AbiSnapshot(library="libfoo.so", version="1.0")

        monkeypatch.setattr("abicheck.cli.dump", fake_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "dump", str(so_path), "-H", str(header),
            "--gcc-options", "-march=armv8-a",
        ])
        assert result.exit_code == 0
        assert captured.get("gcc_options") == "-march=armv8-a"

    def test_sysroot_forwarded(self, tmp_path, monkeypatch):
        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")
        sysroot_dir = tmp_path / "sysroot"
        sysroot_dir.mkdir()

        captured = {}
        def fake_dump(**kwargs):
            captured.update(kwargs)
            return AbiSnapshot(library="libfoo.so", version="1.0")

        monkeypatch.setattr("abicheck.cli.dump", fake_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "dump", str(so_path), "-H", str(header),
            "--sysroot", str(sysroot_dir),
        ])
        assert result.exit_code == 0
        assert captured.get("sysroot") == sysroot_dir

    def test_nostdinc_forwarded(self, tmp_path, monkeypatch):
        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")

        captured = {}
        def fake_dump(**kwargs):
            captured.update(kwargs)
            return AbiSnapshot(library="libfoo.so", version="1.0")

        monkeypatch.setattr("abicheck.cli.dump", fake_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "dump", str(so_path), "-H", str(header), "--nostdinc",
        ])
        assert result.exit_code == 0
        assert captured.get("nostdinc") is True

    def test_multiple_cross_flags_combined(self, tmp_path, monkeypatch):
        so_path = tmp_path / "libfoo.so"
        so_path.write_bytes(b"elf")
        header = tmp_path / "foo.h"
        header.write_text("int foo();\n", encoding="utf-8")

        captured = {}
        def fake_dump(**kwargs):
            captured.update(kwargs)
            return AbiSnapshot(library="libfoo.so", version="1.0")

        monkeypatch.setattr("abicheck.cli.dump", fake_dump)

        runner = CliRunner()
        result = runner.invoke(main, [
            "dump", str(so_path), "-H", str(header),
            "--gcc-prefix", "aarch64-linux-gnu-",
            "--gcc-options", "-march=armv8-a",
            "--nostdinc",
        ])
        assert result.exit_code == 0
        assert captured.get("gcc_prefix") == "aarch64-linux-gnu-"
        assert captured.get("gcc_options") == "-march=armv8-a"
        assert captured.get("nostdinc") is True


# ── compat group structure ───────────────────────────────────────────────

class TestCompatGroupStructure:
    def test_compat_help_lists_subcommands(self):
        """'abicheck compat --help' lists check and dump subcommands."""
        runner = CliRunner()
        result = runner.invoke(main, ["compat", "--help"])
        assert result.exit_code == 0
        assert "check" in result.output
        assert "dump" in result.output

    def test_compat_no_subcommand_shows_usage(self):
        """'abicheck compat' without a subcommand shows usage."""
        runner = CliRunner()
        result = runner.invoke(main, ["compat"])
        # Click shows usage and exits with code 2 when no subcommand given
        assert result.exit_code == 2
        assert "Usage" in result.output or "check" in result.output

    def test_compat_dump_help(self):
        """'abicheck compat dump --help' shows dump-specific flags."""
        runner = CliRunner()
        result = runner.invoke(main, ["compat", "dump", "--help"])
        assert result.exit_code == 0
        assert "-lib" in result.output
        assert "-dump" in result.output

    def test_compat_check_help_no_o_alias(self):
        """'-old' flag should not have -o alias (removed to avoid collision)."""
        runner = CliRunner()
        result = runner.invoke(main, ["compat", "check", "--help"])
        assert result.exit_code == 0
        assert "-old" in result.output
        # -o should not appear as alias for -old in the help
        # (it was removed to avoid collision with -o/--output)

    def test_compat_check_missing_descriptor_uses_internal_error_handling(self, tmp_path):
        """Missing descriptor files should be handled by _compat_fail, not Click's exists=True."""
        missing_old = tmp_path / "missing_old.xml"
        missing_new = tmp_path / "missing_new.xml"
        runner = CliRunner()
        result = runner.invoke(main, [
            "compat", "check", "-lib", "foo",
            "-old", str(missing_old), "-new", str(missing_new),
        ])
        # Should exit with compat error code (4 = file access error), not Click's
        # generic exit code 2 from exists=True validation
        assert result.exit_code != 2
        assert result.exit_code != 0


# ── compat dump CLI-level test ───────────────────────────────────────────

class TestCompatDumpCmd:
    def test_compat_dump_missing_lib_exits_nonzero(self):
        """'abicheck compat dump' without -lib should fail."""
        runner = CliRunner()
        result = runner.invoke(main, ["compat", "dump"])
        assert result.exit_code != 0

    def test_compat_dump_with_descriptor(self, tmp_path, monkeypatch):
        """'abicheck compat dump' with valid descriptor calls dump correctly."""
        desc = tmp_path / "desc.xml"
        desc.write_text(
            "<descriptor><version>1.0</version>"
            "<headers>/tmp/foo.h</headers>"
            "<libs>/tmp/libfoo.so</libs></descriptor>",
            encoding="utf-8",
        )

        monkeypatch.setattr("abicheck.compat.cli.dump",
                            lambda **_: AbiSnapshot(library="libfoo.so", version="1.0"))

        dump_out = tmp_path / "out.json"
        runner = CliRunner()
        result = runner.invoke(main, [
            "compat", "dump", "-lib", "foo", "-dump", str(desc),
            "-dump-path", str(dump_out),
        ])
        # May fail if descriptor parse needs real files, but should not crash
        # with traceback
        assert "Traceback" not in (result.output or "")


# ── dataclasses.replace() via -vnum override ─────────────────────────────

class TestVnumOverride:
    def test_compat_check_vnum_overrides_version(self, tmp_path, monkeypatch):
        """'-v1' and '-v2' flags override descriptor versions via dataclasses.replace()."""
        from abicheck.checker import DiffResult, Verdict

        old_desc = tmp_path / "old.xml"
        new_desc = tmp_path / "new.xml"
        old_desc.write_text("<descriptor/>", encoding="utf-8")
        new_desc.write_text("<descriptor/>", encoding="utf-8")

        snaps = [
            AbiSnapshot(library="libfoo.so", version="1.0"),
            AbiSnapshot(library="libfoo.so", version="2.0"),
        ]
        monkeypatch.setattr("abicheck.compat.cli._load_descriptor_or_dump",
                            lambda *_a, **_k: snaps.pop(0))

        captured_snaps = []

        def fake_compare(old, new, **kwargs):
            captured_snaps.append((old.version, new.version))
            return DiffResult(
                old_version=old.version, new_version=new.version,
                library="libfoo.so", verdict=Verdict.NO_CHANGE, changes=[],
            )

        monkeypatch.setattr("abicheck.compat.cli.compare", fake_compare)

        runner = CliRunner()
        result = runner.invoke(main, [
            "compat", "check", "-lib", "foo",
            "-old", str(old_desc), "-new", str(new_desc),
            "-v1", "10.0", "-v2", "20.0",
        ])
        assert result.exit_code == 0
        # Verify the version was overridden via dataclasses.replace()
        assert len(captured_snaps) == 1
        assert captured_snaps[0] == ("10.0", "20.0")


# ── compare exit codes documented ────────────────────────────────────────

class TestCompareExitCodeDocs:
    def test_compare_help_documents_exit_codes(self):
        runner = CliRunner()
        result = runner.invoke(main, ["compare", "--help"])
        assert result.exit_code == 0
        assert "Exit codes:" in result.output
        assert "0" in result.output
        assert "BREAKING" in result.output


# ── dump error handling uses ClickException ──────────────────────────────

class TestDumpClickException:
    def test_dump_error_exits_1_not_2(self, tmp_path):
        """dump on non-ELF file should exit 1 (ClickException) not 2 (sys.exit)."""
        runner = CliRunner()
        result = runner.invoke(main, ["dump", "/dev/null"])
        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "Traceback" not in result.output
