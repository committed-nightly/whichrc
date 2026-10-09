"""Tests for the oracle, including the one promise it makes."""

from __future__ import annotations

from pathlib import Path

import pytest

from whichrc import probe
from whichrc.modes import MODES, Mode

from .conftest import BASH, fake_shell, needs_bash, sentinel_text, write

LOGIN_INTERACTIVE = next(m for m in MODES if m.name == "login interactive")
INTERACTIVE = next(m for m in MODES if m.name == "interactive")
COMMAND = next(m for m in MODES if m.name == "command")
OVER_SSH = next(m for m in MODES if m.name == "command over ssh")
AS_SH_LOGIN = next(m for m in MODES if m.name == "as sh, login")

NAMES = (".bashrc", ".bash_profile", ".bash_login", ".bash_logout", ".profile")


# --- the promise ---------------------------------------------------------


def test_probing_never_executes_the_users_files(tmp_path: Path, home: Path) -> None:  # noqa: F811
    """The whole design. If this fails, whichrc is a program that runs your
    dotfiles in order to tell you about them, which nobody asked for."""
    marker = tmp_path / "it-ran"
    for name in NAMES:
        write(home, name, sentinel_text(marker))

    shell = fake_shell(tmp_path, [".bash_profile", ".profile"])
    for mode in MODES:
        probe.observe(shell, mode, NAMES, timeout=5)

    assert not marker.exists(), "a startup file was executed"
    # And the originals are untouched, not just unexecuted.
    assert (home / ".bashrc").read_text() == sentinel_text(marker)


@needs_bash
def test_bash_env_is_scrubbed_from_the_probe(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BASH_ENV names a file for bash to run in exactly the mode whichrc
    probes most. Inherited, it would run one of the user's real files."""
    marker = tmp_path / "bash-env-ran"
    victim = write(home, ".bash_env_file", sentinel_text(marker))
    monkeypatch.setenv("BASH_ENV", str(victim))

    probe.observe(Path(BASH), COMMAND, NAMES, timeout=5)

    assert not marker.exists()


# --- the measurement -----------------------------------------------------


def test_rounds_recover_an_unknown_precedence_chain(tmp_path: Path) -> None:
    shell = fake_shell(tmp_path, [".bash_login", ".profile", ".bashrc"])
    result = probe.observe(shell, LOGIN_INTERACTIVE, NAMES, timeout=5)

    assert result.read_now == (".bash_login",)
    assert result.rounds == ((".bash_login",), (".profile",), (".bashrc",))
    # Nothing in the chain, so never read by this shell at all.
    assert result.round_of(".bash_profile") is None


def test_a_shell_that_reads_nothing_has_no_rounds(tmp_path: Path) -> None:
    shell = fake_shell(tmp_path, [])
    assert probe.observe(shell, LOGIN_INTERACTIVE, NAMES, timeout=5).rounds == ()


def test_no_candidates_means_no_work(tmp_path: Path) -> None:
    shell = fake_shell(tmp_path, [".profile"])
    assert probe.observe(shell, LOGIN_INTERACTIVE, (), timeout=5).rounds == ()


def test_blame_drops_a_file_that_was_only_read_alongside(tmp_path: Path) -> None:
    """Two files read in one round are not both the reason for the third.

    bash reads ~/.bash_profile on the way in and ~/.bash_logout on the way
    out; only the first is why ~/.bash_login never runs. Modelled here as a
    shell that always reads the logout file, whichever profile it picked.
    """
    shell = tmp_path / "withlogout"
    shell.write_text(
        "#!/bin/sh\n"
        'for f in .bash_profile .bash_login; do\n'
        '  if [ -f "$HOME/$f" ]; then . "$HOME/$f"; break; fi\n'
        "done\n"
        '[ -f "$HOME/.bash_logout" ] && . "$HOME/.bash_logout"\n'
        "exit 0\n"
    )
    shell.chmod(0o755)

    result = probe.observe(shell, LOGIN_INTERACTIVE, NAMES, timeout=5)
    assert set(result.read_now) == {".bash_profile", ".bash_logout"}

    index = result.round_of(".bash_login")
    assert index == 1
    earlier = tuple(n for r in result.rounds[:index] for n in r)
    assert set(earlier) == {".bash_profile", ".bash_logout"}
    assert probe.blame(shell, LOGIN_INTERACTIVE, NAMES, ".bash_login", earlier) == (
        ".bash_profile",
    )


# --- what bash on this machine actually does -----------------------------


@needs_bash
def test_bash_login_interactive_reads_the_logout_file() -> None:
    """The regression that made this probe stop using `-c :`.

    ~/.bash_logout only runs when an interactive login shell exits normally,
    so a probe that hands bash a command string never sees it and reports a
    file bash reads every time you log out as a file nothing reads.
    """
    names = (".bash_profile", ".bash_logout")
    result = probe.observe(Path(BASH), LOGIN_INTERACTIVE, names, timeout=5)
    assert result.read_now == (".bash_profile", ".bash_logout")


@needs_bash
def test_bash_login_interactive_does_not_read_bashrc() -> None:
    names = (".bash_profile", ".bashrc")
    login = probe.observe(Path(BASH), LOGIN_INTERACTIVE, names, timeout=5)
    interactive = probe.observe(Path(BASH), INTERACTIVE, names, timeout=5)

    assert login.read_now == (".bash_profile",)
    assert interactive.read_now == (".bashrc",)


@needs_bash
def test_bash_login_prefers_bash_profile_over_profile() -> None:
    names = (".bash_profile", ".bash_login", ".profile")
    result = probe.observe(Path(BASH), LOGIN_INTERACTIVE, names, timeout=5)
    assert result.read_now == (".bash_profile",)
    assert result.round_of(".profile") == 2


@needs_bash
def test_bash_called_as_sh_reads_profile() -> None:
    names = (".bash_profile", ".profile")
    result = probe.observe(Path(BASH), AS_SH_LOGIN, names, timeout=5)
    assert result.read_now == (".profile",)


def test_the_probe_environment_drops_shlvl_and_the_file_naming_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The invariant behind the SHLVL fix, asserted where it cannot be vacuous.

    bash's "was I started by sshd" branch is also gated on `shell_level < 2`,
    so a probe that inherits SHLVL from the shell that ran whichrc reports
    that `ssh host cmd` does not read ~/.bashrc on a machine where it does.
    A shell started by sshd or by login is top-level, so the probe must be.
    """
    for var in ("SHLVL", "BASH_ENV", "ENV", "ZDOTDIR"):
        monkeypatch.setenv(var, "3" if var == "SHLVL" else "/home/you/something")
    env = probe._probe_env(tmp_path, COMMAND)
    assert "SHLVL" not in env
    for var in probe.SCRUBBED:
        assert var not in env
    assert env["HOME"] == str(tmp_path)


@needs_bash
def test_the_parent_shell_level_does_not_change_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same thing through the front door, on the mode where it showed up.

    Vacuous on a bash without SSH_SOURCE_BASHRC, where both answers are
    "nothing". Not vacuous on one with it, which is what Ubuntu ships.
    """
    answers = []
    for level in (None, "1", "5"):
        monkeypatch.delenv("SHLVL", raising=False)
        if level is not None:
            monkeypatch.setenv("SHLVL", level)
        result = probe.observe(Path(BASH), OVER_SSH, (".bashrc",), timeout=5)
        if result.unprobed:
            pytest.skip(f"no loopback socket here: {result.unprobed}")
        answers.append(result.rounds)
    assert len(set(answers)) == 1, answers


@needs_bash
def test_the_ssh_mode_never_reads_less_than_the_plain_command_mode() -> None:
    """Whether `ssh host cmd` reads ~/.bashrc is a build-time option plus a
    getpeername() check, so the answer belongs to the machine. What holds on
    any build is that the ssh shape is the plain shape with more reasons to
    read something -- so if this ever reads *less*, the socket plumbing or the
    environment has broken, not bash."""
    names = (".bashrc",)
    plain = probe.observe(Path(BASH), COMMAND, names, timeout=5)
    over_ssh = probe.observe(Path(BASH), OVER_SSH, names, timeout=5)
    if over_ssh.unprobed:
        pytest.skip(f"no loopback socket here: {over_ssh.unprobed}")
    assert set(plain.read_now) <= set(over_ssh.read_now)


@needs_bash
def test_the_ssh_mode_gets_a_real_socket_or_says_so() -> None:
    """Whether bash reads ~/.bashrc for `ssh host cmd` is a build-time option
    (SSH_SOURCE_BASHRC) plus a getpeername() check, so the answer is whatever
    this bash does. The test asserts the probe ran, not which way it went."""
    result = probe.observe(Path(BASH), OVER_SSH, (".bashrc",), timeout=5)
    if result.unprobed:
        pytest.skip(f"no loopback socket here: {result.unprobed}")
    assert result.rounds in ((), ((".bashrc",),))


def test_a_timeout_keeps_what_was_read_before_it(tmp_path: Path) -> None:
    """A shell that hangs after sourcing something still told us something."""
    shell = tmp_path / "hangs"
    shell.write_text(
        '#!/bin/sh\nif [ -f "$HOME/.profile" ]; then . "$HOME/.profile"; fi\nsleep 30\n'
    )
    shell.chmod(0o755)
    result = probe.observe(shell, Mode("slow", "", ()), (".profile",), timeout=1.0)
    assert result.read_now == (".profile",)
