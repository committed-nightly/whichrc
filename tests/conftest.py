from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="no bash on this machine")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    where = tmp_path / "home"
    where.mkdir()
    return where


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No inherited SHELL or entry-point variables leaking into a test.

    Several of these change the report, and a test that passes only on a
    machine whose SHELL happens to be bash is not a test.
    """
    for var in ("BASH_ENV", "ENV", "ZDOTDIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SHELL", BASH or "/bin/sh")


def write(home: Path, name: str, text: str = "true\n") -> Path:
    path = home / name
    path.write_text(text)
    return path


def fake_shell(tmp_path: Path, prefers: list[str], name: str = "fakesh") -> Path:
    """A shell that reads the first file in `prefers` that exists.

    Used so the elimination algorithm is tested against a known precedence
    chain rather than against whatever bash on this machine happens to do.
    """
    path = tmp_path / name
    body = ["#!/bin/sh", "# a shell, for the purposes of this test only"]
    for candidate in prefers:
        body.append(f'if [ -f "$HOME/{candidate}" ]; then . "$HOME/{candidate}"; exit 0; fi')
    body.append("exit 0")
    path.write_text("\n".join(body) + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def sentinel_text(marker: Path) -> str:
    """A startup file that leaves proof behind if anything ever runs it."""
    return f'printf x > {marker}\necho "this should never be executed by whichrc"\n'


def listdir(path: Path) -> list[str]:
    return sorted(os.listdir(path))
