"""Turn the probe's rounds into an answer about this home directory."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import candidates as cand
from . import mentions as men
from . import probe as pr
from . import shells as sh
from .modes import modes_for

#: Environment variables that give the shell another file to run. whichrc
#: scrubs these from the probe so it cannot execute one of your real files,
#: which means it also cannot tell you what they do. Reported as a note.
ENTRY_VARS = ("BASH_ENV", "ENV", "ZDOTDIR")


@dataclass(frozen=True)
class ShellReport:
    shell: sh.Shell
    modes: tuple[pr.ModeResult, ...] = ()


@dataclass(frozen=True)
class Finding:
    name: str
    #: The absolute path, for -q and --json, which are meant to be grepped.
    path: str
    code: str
    message: str

    def line(self) -> str:
        return f"{self.path}: {self.code}: {self.message}"


@dataclass
class Report:
    home: Path
    candidates: list[cand.Candidate] = field(default_factory=list)
    shells: list[sh.Shell] = field(default_factory=list)
    per_shell: list[ShellReport] = field(default_factory=list)
    login: "LoginStory | None" = None
    findings: list[Finding] = field(default_factory=list)
    mentions: list[men.Mention] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def display(self, name: str) -> str:
        """The short form for the human report, whose heading names the directory."""
        return f"~/{name}" if self.home == Path(os.path.expanduser("~")) else name

    def path_of(self, name: str) -> str:
        return str(self.home / name)


def _joined(report: "Report", names: tuple[str, ...]) -> str:
    shown = [report.display(n) for n in names]
    if len(shown) == 1:
        return shown[0]
    return ", ".join(shown[:-1]) + f" and {shown[-1]}"


def _read_now_anywhere(per_shell: list[ShellReport], name: str) -> bool:
    return any(name in m.read_now for r in per_shell for m in r.modes)


def _first_later_round(
    per_shell: list[ShellReport], name: str
) -> tuple[sh.Shell, pr.ModeResult, int] | None:
    """The first place the file would be read if earlier ones were gone."""
    best: tuple[sh.Shell, pr.ModeResult, int] | None = None
    for report in per_shell:
        for mode in report.modes:
            index = mode.round_of(name)
            if index is None or index == 0:
                continue
            if best is None or index < best[2]:
                best = (report.shell, mode, index)
    return best


def _unread_reason(shells: list[sh.Shell], name: str) -> str:
    wanted = cand.FAMILY_SHELLS.get(cand.family_of(name), ())
    probed = {s.name for s in sh.probeable(shells)}
    if not wanted or (set(wanted) & probed):
        return "no shell here reads it in any mode, even with every other startup file removed"
    # The file belongs to a shell nobody asked. Whether that is because it is
    # not installed or because --shell left it out is a different sentence,
    # and getting it wrong makes the tool sound surer than it is.
    absent = [n for n in wanted if shutil.which(n) is None]
    if absent:
        which = " or ".join(absent)
        return f"no shell here reads this name; {which} is not installed on this machine"
    which = " or ".join(n for n in wanted if n not in probed)
    return f"no shell here reads this name; {which} is installed but whichrc did not probe it"


def _findings(report: Report, timeout: float) -> list[Finding]:
    all_names = tuple(c.name for c in report.candidates)
    found: list[Finding] = []
    for candidate in report.candidates:
        name = candidate.name
        if _read_now_anywhere(report.per_shell, name):
            continue
        later = _first_later_round(report.per_shell, name)
        if later is not None:
            shell, mode, index = later
            earlier = tuple(n for r in mode.rounds[:index] for n in r)
            blamed = pr.blame(
                shell.path, mode.mode, all_names, name, earlier, timeout=timeout
            )
            # Empty would mean the shell read it with everything in place,
            # which contradicts the round it came from. Trust the round.
            blamed = blamed or earlier
            found.append(
                Finding(
                    name,
                    report.path_of(name),
                    "shadowed",
                    f"{shell.name} would read it in {mode.mode.name} "
                    f"only if {_joined(report, blamed)} were gone",
                )
            )
            continue
        found.append(
            Finding(name, report.path_of(name), "unread", _unread_reason(report.shells, name))
        )
    return found


#: The mode people mean when they say "my shell". It is also the mode whose
#: answer surprises people most, because it is not the one that reads
#: ~/.bashrc.
LOGIN_MODE = "login interactive"


@dataclass(frozen=True)
class Missing:
    """A startup file your login shell does not read, and why not."""

    name: str
    reason: str
    #: A line in a file that does run, naming this file. Text, not observed.
    mention: men.Mention | None = None


@dataclass(frozen=True)
class LoginStory:
    shell: sh.Shell
    runs: tuple[str, ...] = ()
    missing: tuple[Missing, ...] = ()
    #: How the shell was chosen, since $SHELL is a claim about you, not a fact.
    chosen: str = ""


def _login_shell(report: Report) -> tuple[sh.Shell, str] | None:
    """The shell a login session would start, and how we decided that."""
    probed = sh.probeable(report.shells)
    if not probed:
        return None
    wanted = Path(os.environ.get("SHELL", "")).name
    for shell in probed:
        if wanted and shell.name == wanted:
            return shell, f"SHELL={os.environ['SHELL']}"
    for shell in probed:
        if shell.name == "bash":
            return shell, "SHELL is not set to a shell found here; showing bash"
    return probed[0], "SHELL is not set to a shell found here; showing the first shell found"


def _login_story(report: Report, timeout: float) -> LoginStory | None:
    chosen = _login_shell(report)
    if chosen is None:
        return None
    shell, why = chosen
    entry = next(e for e in report.per_shell if e.shell is shell)
    login = next((m for m in entry.modes if m.mode.name == LOGIN_MODE), None)
    if login is None or login.unprobed:
        return LoginStory(shell, chosen=why)

    runs = login.read_now
    all_names = tuple(c.name for c in report.candidates)
    by_name = {c.name: c for c in report.candidates}
    read_here = [by_name[n] for n in runs if n in by_name]
    missing: list[Missing] = []
    for name in all_names:
        if name in runs:
            continue
        # "bash does not read ~/.zshrc" is true and nobody needed telling. A
        # file belonging to another shell's family is that shell's business,
        # and the findings below still cover it if nothing reads it at all.
        if shell.name not in cand.FAMILY_SHELLS.get(cand.family_of(name), ()):
            continue
        index = login.round_of(name)
        if index is not None:
            earlier = tuple(n for r in login.rounds[:index] for n in r)
            blamed = pr.blame(shell.path, login.mode, all_names, name, earlier, timeout) or earlier
            reason = f"only if {_joined(report, blamed)} were gone"
        else:
            elsewhere = [
                m.mode.name for m in entry.modes if name in m.read_now and m.mode.name != LOGIN_MODE
            ]
            if elsewhere:
                where = (
                    elsewhere[0]
                    if len(elsewhere) == 1
                    else ", ".join(elsewhere[:-1]) + f" and {elsewhere[-1]}"
                )
                reason = f"{shell.name} reads it in {where}, but not here"
            else:
                reason = f"{shell.name} does not read it in any mode"
        found = men.scan(read_here, [name])
        missing.append(Missing(name, reason, found[0] if found else None))
    return LoginStory(shell, runs, tuple(missing), why)


def _notes(home: Path) -> list[str]:
    notes: list[str] = []
    for var in ENTRY_VARS:
        value = os.environ.get(var)
        if not value:
            continue
        if var == "ZDOTDIR":
            where = Path(value).expanduser()
            if where != home:
                notes.append(
                    f"ZDOTDIR={value} is set, so zsh looks for its startup files there, "
                    f"not in {home}. Run whichrc --home {value} to ask about those."
                )
            continue
        notes.append(
            f"{var}={value} is set. The shell runs that file too, in modes this report "
            f"shows as reading nothing. whichrc does not probe it, because probing it "
            f"would mean running one of your real files."
        )
    return notes


def run(
    home: Path,
    shell_paths: list[Path] | None = None,
    timeout: float = pr.DEFAULT_TIMEOUT,
) -> Report:
    """Probe every shell against every candidate file in `home`."""
    home = home.expanduser()
    found = cand.find(home)
    if shell_paths:
        discovered = [
            sh.Shell(p.name, p, version=sh.version_of(p)) if p.exists()
            else sh.Shell(p.name, p, skipped="no such file")
            for p in shell_paths
        ]
    else:
        discovered = sh.discover()
    report = Report(home=home, candidates=found, shells=discovered, notes=_notes(home))

    names = tuple(c.name for c in found)
    for shell in sh.probeable(discovered):
        results = tuple(
            pr.observe(shell.path, mode, names, timeout=timeout)
            for mode in modes_for(shell.name)
        )
        report.per_shell.append(ShellReport(shell, results))

    report.login = _login_story(report, timeout)
    report.findings = _findings(report, timeout)
    started = [c for c in found if _read_now_anywhere(report.per_shell, c.name)]
    unread_names = [f.name for f in report.findings]
    report.mentions = men.scan(started, unread_names)
    return report
