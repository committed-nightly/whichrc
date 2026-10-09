"""Tests for the command line and the shape of what it prints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whichrc import cli

from .conftest import BASH, needs_bash, write


def run(args: list[str], capsys: pytest.CaptureFixture) -> tuple[int, str, str]:
    code = cli.main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@needs_bash
def test_exit_1_when_a_startup_file_is_never_read(
    home: Path, capsys: pytest.CaptureFixture, clean_env
) -> None:
    write(home, ".bash_profile")
    write(home, ".bash_login")
    code, out, _ = run(["--home", str(home)], capsys)
    assert code == 1
    assert ".bash_login" in out


@needs_bash
def test_exit_0_when_everything_is_read(
    home: Path, capsys: pytest.CaptureFixture, clean_env
) -> None:
    write(home, ".bash_profile")
    code, out, _ = run(["--home", str(home)], capsys)
    assert code == 0
    assert "Every startup file here is read by something." in out


def test_exit_2_on_a_home_that_is_not_there(capsys: pytest.CaptureFixture) -> None:
    code, out, err = run(["--home", "/no/such/home"], capsys)
    assert code == 2
    assert "is not a directory" in err
    assert out == ""


def test_an_empty_home_says_so_rather_than_printing_a_table(
    home: Path, capsys: pytest.CaptureFixture, clean_env
) -> None:
    code, out, _ = run(["--home", str(home)], capsys)
    assert code == 0
    assert out.strip() == f"No startup files in {home}. Nothing to say."


@needs_bash
def test_quiet_prints_findings_only(
    home: Path, capsys: pytest.CaptureFixture, clean_env
) -> None:
    write(home, ".bash_profile")
    write(home, ".bash_login")
    code, out, _ = run(["--home", str(home), "-q"], capsys)
    assert code == 1
    lines = out.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(f"{home}/.bash_login: shadowed: ")


@needs_bash
def test_json_is_json_and_carries_the_rounds(
    home: Path, capsys: pytest.CaptureFixture, clean_env
) -> None:
    write(home, ".bash_profile")
    write(home, ".bash_login")
    code, out, _ = run(["--home", str(home), "--json"], capsys)
    assert code == 1
    payload = json.loads(out)
    assert payload["home"] == str(home)
    bash = next(s for s in payload["observed"] if s["shell"] == "bash")
    login = next(m for m in bash["modes"] if m["mode"] == "login interactive")
    assert login["reads"] == [".bash_profile"]
    assert login["rounds"] == [[".bash_profile"], [".bash_login"]]
    assert payload["findings"][0]["code"] == "shadowed"


@needs_bash
def test_the_shell_flag_narrows_what_gets_probed(
    home: Path, capsys: pytest.CaptureFixture, clean_env
) -> None:
    write(home, ".bash_profile")
    _, out, _ = run(["--home", str(home), "--shell", BASH, "--json"], capsys)
    payload = json.loads(out)
    assert [s["name"] for s in payload["shells"]] == ["bash"]
