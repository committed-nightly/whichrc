"""The ways a shell gets started, and what each one is in real life.

Most modes hand the shell /dev/null as stdin and no command, which is what a
shell session looks like from the shell's side: it reads commands until end of
input, then exits. That shape matters. A shell started with `-c` never runs
~/.bash_logout, because the logout file belongs to a login shell that exits
normally -- so a probe built on `-c :` would report ~/.bash_logout as a file
nothing reads, which is wrong, and wrong in the confident direction.

The two `-c` modes are kept because `-c` is itself a condition: bash's check
for "was I started by sshd" only applies to a shell that was given a command
string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

#: A documentation-only address (RFC 5737). The shell reads this out of the
#: environment; nothing ever connects to it.
SSH_CLIENT = "203.0.113.1 54321 203.0.113.9 22"


@dataclass(frozen=True)
class Mode:
    name: str
    #: What you would actually be doing, for the legend.
    real_life: str
    args: tuple[str, ...] = ()
    #: Run the same binary under a different argv[0]. Shells change behaviour
    #: when called `sh`, and /bin/sh being a symlink does that to you without
    #: mentioning it.
    argv0: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    #: "devnull", or "inet" for a real loopback TCP socket. bash decides
    #: whether it was started by sshd partly by asking the kernel whether its
    #: stdin is a network connection, and that cannot be faked with a variable.
    stdin: str = "devnull"


MODES: tuple[Mode, ...] = (
    Mode(
        "login interactive",
        "ssh you@host, or a login terminal; includes what runs on the way out",
        ("-l", "-i"),
    ),
    Mode("login", "su - you, or a display manager starting your session", ("-l",)),
    Mode("interactive", "typing the shell's name in a terminal you already have", ("-i",)),
    Mode("command", "shell -c '...', a Makefile recipe, a cron job", ("-c", ":")),
    Mode(
        "command over ssh",
        "ssh you@host 'some command' -- a command string, with a socket for stdin",
        ("-c", ":"),
        env={"SSH_CLIENT": SSH_CLIENT},
        stdin="inet",
    ),
    Mode("as sh, login", "/bin/sh -l, on a machine where /bin/sh is this shell", ("-l",), argv0="sh"),
    Mode("as sh, interactive", "/bin/sh in a terminal", ("-i",), argv0="sh"),
)


def modes_for(shell_name: str) -> tuple[Mode, ...]:
    """Every mode, minus the ones that would say the same thing twice.

    A shell already called `sh` has nothing to learn from being called `sh`.
    """
    if shell_name == "sh":
        return tuple(m for m in MODES if m.argv0 is None)
    return MODES
