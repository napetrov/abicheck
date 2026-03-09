from __future__ import annotations

from types import SimpleNamespace

from click.testing import CliRunner

from abicheck.checker import Change, ChangeKind, DiffResult, Verdict
from abicheck.cli import main
from abicheck.model import AbiSnapshot


def _snap(version: str = "1.0") -> AbiSnapshot:
    return AbiSnapshot(library="libfoo.so", version=version)


def test_dump_cmd_writes_output_file(tmp_path, monkeypatch):
    so_path = tmp_path / "libfoo.so"
    so_path.write_bytes(b"elf")
    header = tmp_path / "foo.h"
    header.write_text("int foo();\n", encoding="utf-8")
    out = tmp_path / "snap.json"

    monkeypatch.setattr("abicheck.cli.dump", lambda **_: _snap("2.0"))

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "dump",
            str(so_path),
            "-H",
            str(header),
            "--version",
            "2.0",
            "-o",
            str(out),
        ],
    )

    assert result.exit_code == 0
    assert "Snapshot written to" in result.stderr
    assert out.exists()
    assert '"version": "2.0"' in out.read_text(encoding="utf-8")


def test_compare_cmd_warns_when_all_changes_suppressed(tmp_path, monkeypatch):
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    suppress = tmp_path / "suppress.yaml"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    suppress.write_text("version: 1\nsuppressions: []\n", encoding="utf-8")

    monkeypatch.setattr("abicheck.cli.load_snapshot", lambda _: _snap())
    monkeypatch.setattr("abicheck.suppression.SuppressionList.load", lambda _: object())
    monkeypatch.setattr(
        "abicheck.cli.compare",
        lambda *_args, **_kwargs: DiffResult(
            old_version="1",
            new_version="2",
            library="libfoo.so",
            verdict=Verdict.COMPATIBLE,
            changes=[],
            suppressed_count=1,
            suppression_file_provided=True,
        ),
    )
    monkeypatch.setattr("abicheck.cli.to_markdown", lambda _r: "REPORT")

    runner = CliRunner()
    result = runner.invoke(main, ["compare", str(old), str(new), "--suppress", str(suppress)])

    assert result.exit_code == 0
    assert "all ABI changes were suppressed" in result.stderr
    assert "REPORT" in result.stdout


def test_compare_cmd_breaking_exits_with_code_4(tmp_path, monkeypatch):
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("abicheck.cli.load_snapshot", lambda _: _snap())
    monkeypatch.setattr(
        "abicheck.cli.compare",
        lambda *_args, **_kwargs: DiffResult(
            old_version="1",
            new_version="2",
            library="libfoo.so",
            verdict=Verdict.BREAKING,
            changes=[Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "removed")],
        ),
    )
    monkeypatch.setattr("abicheck.cli.to_markdown", lambda _r: "BREAKING REPORT")

    runner = CliRunner()
    result = runner.invoke(main, ["compare", str(old), str(new)])

    assert result.exit_code == 4
    assert "BREAKING REPORT" in result.stdout


def test_compat_cmd_descriptor_parse_error_exits_2(tmp_path, monkeypatch):
    old_desc = tmp_path / "old.xml"
    new_desc = tmp_path / "new.xml"
    old_desc.write_text("<xml/>", encoding="utf-8")
    new_desc.write_text("<xml/>", encoding="utf-8")

    monkeypatch.setattr("abicheck.cli.parse_descriptor", lambda *_, **__: (_ for _ in ()).throw(ValueError("bad")))

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["compat", "-lib", "foo", "-old", str(old_desc), "-new", str(new_desc)],
    )

    assert result.exit_code == 2
    assert "Error parsing descriptor" in result.stderr


def test_compat_cmd_breaking_exits_1_and_writes_report(tmp_path, monkeypatch):
    old_desc = tmp_path / "old.xml"
    new_desc = tmp_path / "new.xml"
    old_desc.write_text("<xml/>", encoding="utf-8")
    new_desc.write_text("<xml/>", encoding="utf-8")

    old_so = tmp_path / "old.so"
    new_so = tmp_path / "new.so"
    old_so.write_bytes(b"elf")
    new_so.write_bytes(b"elf")

    old_d = SimpleNamespace(libs=[old_so], headers=[], version="1.0")
    new_d = SimpleNamespace(libs=[new_so], headers=[], version="2.0")

    monkeypatch.setattr("abicheck.cli.parse_descriptor", lambda p, **_kw: old_d if p == old_desc else new_d)
    monkeypatch.setattr("abicheck.cli.dump", lambda *_args, **_kwargs: _snap())
    monkeypatch.setattr(
        "abicheck.cli.compare",
        lambda *_args, **_kwargs: DiffResult(
            old_version="1.0",
            new_version="2.0",
            library="libfoo.so",
            verdict=Verdict.BREAKING,
            changes=[Change(ChangeKind.FUNC_REMOVED, "_Z3foov", "removed")],
        ),
    )

    report = tmp_path / "compat" / "report.json"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "compat",
            "-lib",
            "foo",
            "-old",
            str(old_desc),
            "-new",
            str(new_desc),
            "-report-format",
            "json",
            "-report-path",
            str(report),
        ],
    )

    assert result.exit_code == 1
    assert report.exists()
    assert "BREAKING" in report.read_text(encoding="utf-8")
    assert "Verdict: BREAKING" in result.stderr
