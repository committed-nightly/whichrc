"""The one thing the probe cannot see.

whichrc measures which files *the shell* opens. It cannot see a file your own
config opens, because it never runs your config -- so if ~/.bash_profile ends
in `. ~/.bashrc`, the probe will still report ~/.bashrc as unread by login
shells, and be wrong about your machine.

This module is the honest patch for that: it reads the text of the files the
shell does start, and says which other startup file names appear in them, with
line numbers. It does not decide whether the line runs, whether the condition
around it holds, or whether it is reached. Everything here is printed under a
heading that says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .candidates import Candidate

#: `. file`, `source file`, and the zsh/bash spellings in between. Only used to
#: label a mention as the stronger kind; a mention that does not match is
#: still reported.
_SOURCING = re.compile(r"(^|[;&|(]|\bthen\b|\belse\b|\bdo\b)\s*(\.|source)\s")


@dataclass(frozen=True)
class Mention:
    #: The file doing the mentioning. The shell does start this one.
    source: Candidate
    #: The candidate file name that appears in it.
    target: str
    line: int
    text: str
    sourcing: bool

    @property
    def verb(self) -> str:
        return "sources" if self.sourcing else "mentions"


def _strip_comment(line: str) -> str:
    """Drop a whole-line comment. Anything subtler is left alone.

    A mid-line `#` is not a comment if it is inside quotes or a parameter
    expansion, and deciding which needs a shell parser. Over-reporting a
    mention is cheap -- the heading already says these are not observed --
    and quoting rules are somebody else's repository (see `quotemap`).
    """
    stripped = line.strip()
    return "" if stripped.startswith("#") else line


def scan(read_files: list[Candidate], targets: list[str]) -> list[Mention]:
    """Find `targets` named in the text of `read_files`."""
    mentions: list[Mention] = []
    for candidate in read_files:
        try:
            text = candidate.path.read_text(errors="replace")
        except OSError:
            continue
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = _strip_comment(raw)
            if not line:
                continue
            for target in targets:
                if target == candidate.name or target not in line:
                    continue
                mentions.append(
                    Mention(
                        source=candidate,
                        target=target,
                        line=lineno,
                        text=raw.strip()[:120],
                        sourcing=bool(_SOURCING.search(line)),
                    )
                )
    return mentions


def home_display(path: Path, home: Path) -> str:
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)
