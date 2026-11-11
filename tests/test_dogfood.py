r"""The claims the dogfood job makes, as tests that run on every machine.

The dogfood job in .github/workflows/ci.yml asserts things about the report
built from examples/build.sh, because the README quotes that report. Two of
its assertions could not do that job, and both were found by `deadassert`
(logbook#64):

* `if grep -q '^/.*\.zshrc: unread' ...; then exit 1; fi` sits inside an
  `if command -v zsh` branch. No runner image this job has run on has had zsh
  on PATH, so the only branch ever taken is the `else`, and the guard has
  never executed. Worse, the branch could not have passed if it had: the job
  pins `SHELL=/usr/bin/bash`, and with bash as the login shell a line that
  *begins* ``  .zshrc`` appears only in the findings block -- which is the one
  thing the guard three lines above forbids.

* `if grep -q '\.bash_logout' findings.txt; then exit 1; fi` passes when the
  pattern is absent, and nothing anywhere established that the pattern could
  appear at all. It also passed on an empty findings list.

The fix in both cases is to stop asking what the runner happens to have.
`--shell` pins the shells, which makes the zsh-present case reachable on a
machine with no zsh and makes the findings list exact rather than
image-dependent.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from whichrc import analyse, report
from whichrc.modes import MODES

from .conftest import BASH, fake_shell, needs_bash

TIMEOUT = 5.0

#: examples/build.sh, which the README tells the reader to run.
BUILD = Path(__file__).resolve().parents[1] / "examples" / "build.sh"


def build_example(home: Path) -> Path:
    """Populate `home` using the example script itself, not a copy of it.

    A fixture that reimplemented build.sh would drift from it, and build.sh
    is the thing the README tells you to run.
    """
    subprocess.run(
        ["sh", str(BUILD), str(home)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return home


def example_report(home: Path, *shells: Path) -> analyse.Report:
    return analyse.run(home, shell_paths=list(shells), timeout=TIMEOUT)


def names(result: analyse.Report) -> list[str]:
    return [f.name for f in result.findings]


def zsh_block(text: str) -> str:
    """The rows under zsh's heading, the way the dogfood job slices them."""
    return text.split("\nzsh  ", 1)[1].split("\n\n", 1)[0]


@needs_bash
def test_the_example_findings_are_exactly_these_two(home: Path, clean_env) -> None:
    """The whole findings list, not an absence check over part of it.

    This is what replaces the `.bash_logout` guard. The guard passed if
    `.bash_logout` was missing from the output *for any reason*, including
    the output being empty; this fails unless the list is exactly these two,
    so a third finding -- `.bash_logout` among them -- fails here.

    It is also the witness the `.zshrc: unread` guard never had: the line
    that guard forbids on a zsh machine is asserted present here, where it is
    the correct answer, so the guard is checking for a line the tool still
    produces rather than one that stopped being printed.
    """
    build_example(home)
    result = example_report(home, Path(BASH))
    assert names(result) == [".bash_login", ".zshrc"]
    assert result.findings[0].line() == (
        f"{home}/.bash_login: shadowed: bash would read it in login interactive "
        "only if .bash_profile were gone"
    )
    # The reason depends on whether this machine has a zsh that went unprobed;
    # the code and the path do not.
    assert result.findings[1].line().startswith(f"{home}/.zshrc: unread: ")


@needs_bash
def test_bash_logout_becomes_a_finding_when_the_probe_cannot_see_logout_files(
    home: Path, clean_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test above, and the one CI could not have.

    `.bash_logout` is absent from the findings list because bash really does
    read it on the way out of a login session. That is only evidence if the
    list can hold it, so here the probe is put back to the `-c :` shape
    modes.py warns about -- the shape the first version of the tool shipped
    with -- and `.bash_logout` duly appears.

    A negated grep in CI cannot be witnessed this way, because witnessing it
    means breaking the probe. That is why this lives here (logbook#64).
    """
    build_example(home)
    broken = (replace(MODES[0], args=("-l", "-i", "-c", ":")),) + MODES[1:]
    monkeypatch.setattr(analyse, "modes_for", lambda name: broken)
    result = example_report(home, Path(BASH))
    assert ".bash_logout" in names(result)
    logout = next(f for f in result.findings if f.name == ".bash_logout")
    assert logout.code == "unread"


@needs_bash
def test_zsh_present_means_zshrc_is_read_and_is_not_a_finding(
    home: Path, tmp_path: Path, clean_env
) -> None:
    """The branch CI has never run, on a machine that does not have zsh.

    `--shell` takes a path, so a shell named `zsh` that reads `~/.zshrc` is
    enough to reach the other answer. The README says this answer exists; up
    to now nothing checked it.
    """
    build_example(home)
    zsh = fake_shell(tmp_path, [".zshrc"], name="zsh")
    result = example_report(home, Path(BASH), zsh)
    assert names(result) == [".bash_login"]
    probed = next(r for r in result.per_shell if r.shell.name == "zsh")
    rows = {m.mode.name: m.read_now for m in probed.modes}
    assert rows["interactive"] == (".zshrc",)


@needs_bash
def test_a_read_zshrc_is_never_indented_like_a_finding(
    home: Path, tmp_path: Path, clean_env
) -> None:
    r"""Why the dogfood job's `grep -q '^  \.zshrc'` could not have passed.

    With zsh installed and bash the login shell -- which is exactly what the
    dogfood job pins -- `.zshrc` appears only on the right-hand side of a
    mode row in zsh's block. Nothing starts a line with it. The old assertion
    was asking for the findings-block shape, in the branch that had just
    forbidden it, so the branch was unsatisfiable rather than merely dead.
    """
    build_example(home)
    zsh = fake_shell(tmp_path, [".zshrc"], name="zsh")
    text = report.text(example_report(home, Path(BASH), zsh))
    assert [line for line in text.splitlines() if line.startswith("  .zshrc")] == []
    assert re.search(r"^  interactive +\.zshrc$", zsh_block(text), re.M)


@needs_bash
def test_the_rendered_findings_block_explains_zshrc_for_this_machine(
    home: Path, clean_env
) -> None:
    """The README's last findings line, without pinning it to one box.

    Which sentence is right here depends on whether this machine has a zsh
    that went unprobed, and that is the point: the README's example output
    says "zsh is not installed on this machine" and says, underneath, that it
    came from a machine with no zsh. Either wording is a correct answer.
    Neither of them being there is not, and the dogfood job's `else` branch
    greps for one of the two.
    """
    build_example(home)
    text = report.text(example_report(home, Path(BASH)))
    lines = [ln for ln in text.splitlines() if ln.startswith("  .zshrc ")]
    assert len(lines) == 1
    assert (
        "no shell here reads this name; zsh is not installed on this machine" in lines[0]
        or "no shell here reads this name; zsh is installed but whichrc did not probe it"
        in lines[0]
    )
