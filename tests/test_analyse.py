"""Tests for turning rounds into an answer."""

from __future__ import annotations

from pathlib import Path

import pytest

from whichrc import analyse

from .conftest import BASH, fake_shell, needs_bash, write


def run(home: Path, shell: Path) -> analyse.Report:
    return analyse.run(home, shell_paths=[shell], timeout=5)


def codes(report: analyse.Report) -> dict[str, str]:
    return {f.name: f.code for f in report.findings}


def test_a_file_nothing_reads_is_a_finding(home: Path, tmp_path: Path, clean_env) -> None:
    write(home, ".profile")
    write(home, ".zshrc")
    report = run(home, fake_shell(tmp_path, [".profile"]))
    assert codes(report) == {".zshrc": "unread"}


def test_a_shadowed_file_is_named_as_shadowed_not_unread(
    home: Path, tmp_path: Path, clean_env
) -> None:
    write(home, ".bash_profile")
    write(home, ".profile")
    report = run(home, fake_shell(tmp_path, [".bash_profile", ".profile"]))
    assert codes(report) == {".profile": "shadowed"}
    message = report.findings[0].message
    assert ".bash_profile" in message and "were gone" in message


def test_a_file_the_shell_reads_is_not_a_finding(home: Path, tmp_path: Path, clean_env) -> None:
    write(home, ".profile")
    report = run(home, fake_shell(tmp_path, [".profile"]))
    assert report.findings == []


def test_findings_carry_an_absolute_path_for_grepping(
    home: Path, tmp_path: Path, clean_env
) -> None:
    write(home, ".zshrc")
    report = run(home, fake_shell(tmp_path, []))
    assert report.findings[0].line().startswith(f"{home}/.zshrc: unread: ")


def test_an_unread_file_whose_shell_is_missing_says_so(
    home: Path, tmp_path: Path, clean_env
) -> None:
    write(home, ".zshrc")
    report = run(home, fake_shell(tmp_path, [".profile"]))
    # The fake shell is not named zsh, so no zsh was probed.
    assert "zsh is not installed" in report.findings[0].message


def test_a_missing_shell_path_is_reported_not_probed(home: Path, clean_env) -> None:
    write(home, ".profile")
    report = analyse.run(home, shell_paths=[Path("/nonexistent/sh")], timeout=5)
    assert report.per_shell == []
    assert report.shells[0].skipped == "no such file"


# --- the login section ---------------------------------------------------


@needs_bash
def test_the_login_story_names_bashrc_as_not_read(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The question the tool exists to answer out loud."""
    monkeypatch.setenv("SHELL", BASH)
    write(home, ".bash_profile", "export EDITOR=vim\n")
    write(home, ".bashrc", "alias ll='ls -la'\n")
    report = analyse.run(home, timeout=5)

    assert report.login is not None
    assert ".bash_profile" in report.login.runs
    missing = {m.name: m for m in report.login.missing}
    assert ".bashrc" in missing
    assert missing[".bashrc"].mention is None


@needs_bash
def test_a_sourcing_line_is_offered_against_the_observed_answer(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHELL", BASH)
    write(home, ".bash_profile", "export EDITOR=vim\n. ~/.bashrc\n")
    write(home, ".bashrc", "alias ll='ls -la'\n")
    report = analyse.run(home, timeout=5)

    missing = {m.name: m for m in report.login.missing}
    mention = missing[".bashrc"].mention
    assert mention is not None
    assert mention.line == 2
    assert mention.sourcing is True


@needs_bash
def test_the_login_story_leaves_another_shells_files_alone(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"bash does not read ~/.zshrc" is true and nobody needed telling."""
    monkeypatch.setenv("SHELL", BASH)
    write(home, ".bash_profile")
    write(home, ".zshrc")
    report = analyse.run(home, timeout=5)
    assert ".zshrc" not in {m.name for m in report.login.missing}


def test_no_startup_files_means_no_findings(home: Path, tmp_path: Path, clean_env) -> None:
    report = run(home, fake_shell(tmp_path, [".profile"]))
    assert report.candidates == []
    assert report.findings == []


def test_notes_mention_bash_env_when_it_is_set(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BASH_ENV", "/home/you/.env.sh")
    write(home, ".profile")
    report = run(home, fake_shell(tmp_path, [".profile"]))
    assert any("BASH_ENV=/home/you/.env.sh" in n for n in report.notes)


def test_notes_mention_zdotdir_when_it_points_elsewhere(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZDOTDIR", "/home/you/.config/zsh")
    write(home, ".profile")
    report = run(home, fake_shell(tmp_path, [".profile"]))
    assert any("ZDOTDIR" in n and "--home" in n for n in report.notes)
