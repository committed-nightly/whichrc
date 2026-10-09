"""Which shells are on this machine.

A shell that is not installed is named in the report rather than dropped from
it. "No shell here reads ~/.zshrc" and "whichrc did not check zsh" are
different answers, and quietly giving the first when you mean the second is
how a tool like this starts lying.

Lookup is shutil.which, i.e. PATH only, on purpose. `command -v` in a shell
answers for functions and aliases too, and a function named after a real tool
will happily tell you the tool is installed when it is not.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Looked for in this order. `sh` is in the list because /bin/sh is its own
#: answer: on this machine it may be dash, on another it is bash, and which
#: one it is decides whether ~/.bashrc is in play for every `sh -c` on the box.
KNOWN = ("bash", "sh", "dash", "zsh", "ksh", "mksh")


@dataclass(frozen=True)
class Shell:
    name: str
    path: Path
    version: str = ""
    #: Set when the name resolves to something whichrc will not probe.
    skipped: str | None = None


def version_of(path: Path) -> str:
    """A version string, or nothing.

    Only stdout counts, and only if it has a digit in it. A shell that does
    not take `--version` complains on stderr, and `/usr/bin/sh: 0: Illegal
    option --` printed in the version column is worse than an empty column.
    """
    for args in (["--version"], ["-c", 'echo "$KSH_VERSION"']):
        try:
            out = subprocess.run(
                [str(path), *args],
                capture_output=True,
                text=True,
                timeout=5,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        lines = out.stdout.strip().splitlines()
        if lines and any(ch.isdigit() for ch in lines[0]):
            return lines[0].strip()
    return ""


def discover(names: tuple[str, ...] = KNOWN) -> list[Shell]:
    """Every known shell on PATH, plus a record for each one that is missing."""
    shells: list[Shell] = []
    seen: dict[Path, str] = {}
    for name in names:
        found = shutil.which(name)
        if found is None:
            shells.append(Shell(name, Path(name), skipped="not installed on this machine"))
            continue
        path = Path(found)
        real = path.resolve()
        # /bin/sh is usually a link to one of the others. Probing the same
        # binary twice under two names would double the table and say the same
        # thing, so the second name is reported as what it is instead -- which
        # is the useful part anyway: "sh is bash here" decides whether every
        # `sh -c` on the box is in bash's rules.
        if real in seen:
            shells.append(
                Shell(name, path, skipped=f"the same binary as {seen[real]} ({real})")
            )
            continue
        seen[real] = name
        if not os.access(path, os.X_OK):
            shells.append(Shell(name, path, skipped="on PATH but not executable"))
            continue
        shells.append(Shell(name, path, version=version_of(path)))
    return shells


def probeable(shells: list[Shell]) -> list[Shell]:
    return [s for s in shells if s.skipped is None]
