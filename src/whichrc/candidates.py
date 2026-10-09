"""The startup file names worth asking about.

This list is only a filter. Nothing here encodes when a shell reads a name --
that is measured, in probe.py, by running the shell. A name on this list that
no shell reads is a finding, not a bug in the list, so the list can afford to
be generous.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Grouped only so the report can say "zsh is not installed" about the right
# files. The groups are not used to decide what gets probed.
FAMILIES: dict[str, tuple[str, ...]] = {
    "bash": (".bashrc", ".bash_profile", ".bash_login", ".bash_logout"),
    "zsh": (".zshenv", ".zprofile", ".zshrc", ".zlogin", ".zlogout"),
    "ksh": (".kshrc", ".mkshrc"),
    "sh": (".profile", ".shrc"),
}

# The shell each family belongs to, for the "no shell here reads this" message.
FAMILY_SHELLS: dict[str, tuple[str, ...]] = {
    "bash": ("bash",),
    "zsh": ("zsh",),
    "ksh": ("ksh", "ksh93", "mksh", "oksh"),
    "sh": ("sh", "dash", "bash", "ksh", "zsh", "mksh"),
}

NAMES: tuple[str, ...] = tuple(n for group in FAMILIES.values() for n in group)


def family_of(name: str) -> str:
    for family, names in FAMILIES.items():
        if name in names:
            return family
    return "sh"


@dataclass(frozen=True)
class Candidate:
    """A startup file that exists in the home directory being examined."""

    name: str
    path: Path

    @property
    def family(self) -> str:
        return family_of(self.name)


def find(home: Path, names: tuple[str, ...] = NAMES) -> list[Candidate]:
    """The candidate names that exist under `home`.

    A dangling symlink is left out: the shell will not read it either, and
    reporting it as unread would be true for the wrong reason.
    """
    found = []
    for name in names:
        path = home / name
        if path.is_file():
            found.append(Candidate(name, path))
    return found
