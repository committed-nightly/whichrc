"""Ask the shell.

whichrc never reads your startup files to work out what runs. It builds a
throwaway home directory containing files with *your file names* and contents
it wrote itself -- one `printf` each -- then starts the real shell binary
pointed at that directory and reads back which markers appeared. The answer
comes from the shell on this machine, which is the only thing that gets a
vote.

Your files are never sourced, parsed or opened by this module. That is the
whole design, and tests/test_probe.py asserts it with a startup file that
would leave a mark if it ever ran.

Shadowing is measured the same way. A login shell reads the first of
~/.bash_profile, ~/.bash_login, ~/.profile that exists -- but rather than
encode that, whichrc probes, deletes whatever got read, and probes again,
until a round reads nothing. The rounds *are* the precedence chain, and they
come out right on a shell whose rules nobody told us.
"""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from .modes import Mode

#: Variables that name a file for the shell to run. Left in the probe's
#: environment they would make the shell execute one of the user's real files,
#: which is the one thing this module promises not to do.
SCRUBBED = ("BASH_ENV", "ENV", "ZDOTDIR", "SHELLOPTS", "BASHOPTS")

#: SHLVL has to go too, for a different reason. bash's "was I started by
#: sshd" branch is also gated on `shell_level < 2`, so a probe run from inside
#: a shell inherits SHLVL=2 and the branch never fires -- and the tool then
#: reports that `ssh host cmd` does not read ~/.bashrc on a machine where it
#: does. The shell a login or sshd starts is top-level, so the probe is too.
#:
#: Found the hard way: the first version of this file had the wrong answer in
#: the README, with an explanation of why bash was not built with
#: SSH_SOURCE_BASHRC. It was.
TOP_LEVEL = ("SHLVL",)

DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class ModeResult:
    mode: Mode
    #: Files read, in the order the shell read them, grouped by round. Round 0
    #: is what runs today; round n is what would run if every file in rounds
    #: 0..n-1 were deleted.
    rounds: tuple[tuple[str, ...], ...] = ()
    #: Set when the probe could not be run at all, e.g. no loopback socket.
    unprobed: str | None = None

    @property
    def read_now(self) -> tuple[str, ...]:
        return self.rounds[0] if self.rounds else ()

    def round_of(self, name: str) -> int | None:
        for i, names in enumerate(self.rounds):
            if name in names:
                return i
        return None


def _replica_text(name: str, log: Path) -> str:
    # POSIX single-quoting, which every shell here agrees on. `printf` is a
    # builtin in all of them, so this works in a shell with no PATH.
    return "printf '%s\\n' {} >> {}\n".format(
        shlex.quote(name), shlex.quote(str(log))
    )


def _write_replica(home: Path, names: Sequence[str], log: Path) -> None:
    for name in names:
        (home / name).write_text(_replica_text(name, log))


@contextmanager
def _stdin_for(mode: Mode) -> Iterator[int]:
    """A file descriptor to hand the shell as stdin.

    The `inet` case needs a real connected TCP socket because bash asks the
    kernel, via getpeername(), whether its stdin is a network connection. An
    AF_UNIX socketpair does not satisfy it and neither does setting SSH_CLIENT
    on its own.
    """
    if mode.stdin != "inet":
        with open(os.devnull, "rb") as fh:
            yield fh.fileno()
        return
    with ExitStack() as stack:
        listener = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = stack.enter_context(socket.create_connection(listener.getsockname()))
        accepted, _ = listener.accept()
        stack.enter_context(accepted)
        # The shell gets the server end, which is the end sshd would hand it.
        del client
        yield accepted.fileno()


def _probe_env(home: Path, mode: Mode) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED + TOP_LEVEL}
    env["HOME"] = str(home)
    env.update(mode.env)
    return env


def _run_once(
    shell: Path, mode: Mode, home: Path, log: Path, timeout: float
) -> tuple[str, ...]:
    if log.exists():
        log.unlink()
    argv = [mode.argv0 or shell.name, *mode.args]
    try:
        with _stdin_for(mode) as fd:
            subprocess.run(
                argv,
                executable=str(shell),
                env=_probe_env(home, mode),
                stdin=fd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=(fd,),
                timeout=timeout,
                check=False,
            )
    except subprocess.TimeoutExpired:
        # The shell did not exit. Whatever it managed to read before we gave up
        # is still true, so the log is read rather than thrown away.
        pass
    if not log.exists():
        return ()
    seen: list[str] = []
    for line in log.read_text().splitlines():
        if line and line not in seen:
            seen.append(line)
    return tuple(seen)


@contextmanager
def _sandbox() -> Iterator[tuple[Path, Path]]:
    with tempfile.TemporaryDirectory(prefix="whichrc-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        yield home, Path(tmp) / "reads.log"


def _reads_with(
    shell: Path,
    mode: Mode,
    home: Path,
    log: Path,
    present: Sequence[str],
    timeout: float,
) -> tuple[str, ...]:
    """What the shell reads when exactly `present` exists in the home dir."""
    for stale in home.iterdir():
        stale.unlink()
    _write_replica(home, present, log)
    read = _run_once(shell, mode, home, log, timeout)
    return tuple(n for n in read if n in present)


def _unprobeable(mode: Mode) -> str | None:
    try:
        with _stdin_for(mode):
            return None
    except OSError as exc:
        return f"could not open a loopback socket: {exc}"


def observe(
    shell: Path,
    mode: Mode,
    names: Sequence[str],
    timeout: float = DEFAULT_TIMEOUT,
) -> ModeResult:
    """Run `shell` in `mode` repeatedly, removing what it read each time."""
    if not names:
        return ModeResult(mode, ())
    reason = _unprobeable(mode)
    if reason:
        return ModeResult(mode, (), unprobed=reason)

    rounds: list[tuple[str, ...]] = []
    with _sandbox() as (home, log):
        remaining = list(names)
        # One round per file at most: every round that is not the last removes
        # at least one name, so this cannot spin.
        for _ in range(len(names) + 1):
            if not remaining:
                break
            read = _reads_with(shell, mode, home, log, remaining, timeout)
            if not read:
                break
            rounds.append(read)
            remaining = [n for n in remaining if n not in read]
    return ModeResult(mode, tuple(rounds))


def blame(
    shell: Path,
    mode: Mode,
    names: Sequence[str],
    target: str,
    candidates: Sequence[str],
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str, ...]:
    """Which of `candidates` actually have to be gone before `target` is read.

    `observe` knows that removing every file read before `target` makes the
    shell read it, but not which of them mattered. Two files read in the same
    round are not necessarily in the same chain -- bash reads ~/.bash_profile
    on the way in and ~/.bash_logout on the way out, and only the first one is
    the reason ~/.bash_login never runs.

    So each candidate is put back, one at a time, and the shell asked again.
    One that can be put back without silencing `target` was never the problem.
    """
    if _unprobeable(mode):
        return tuple(candidates)
    needed = list(candidates)
    with _sandbox() as (home, log):
        for suspect in list(candidates):
            trial = [n for n in names if n not in needed or n == suspect]
            if target in _reads_with(shell, mode, home, log, trial, timeout):
                needed.remove(suspect)
    return tuple(needed)
