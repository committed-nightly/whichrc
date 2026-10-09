"""Printing. Observed things and read-from-the-text things never share a heading."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Iterator

from .analyse import Report
from .shells import probeable

NOTHING = "nothing"


def _mode_rows(report: Report) -> Iterator[str]:
    for entry in report.per_shell:
        shell = entry.shell
        head = f"{shell.name}  {shell.path}"
        if shell.version:
            head += f"  ({shell.version})"
        yield head
        width = max((len(m.mode.name) for m in entry.modes), default=0)
        for result in entry.modes:
            if result.unprobed:
                value = f"not probed: {result.unprobed}"
            elif result.read_now:
                value = " then ".join(report.display(n) for n in result.read_now)
            else:
                value = NOTHING
            yield f"  {result.mode.name.ljust(width)}  {value}"
        yield ""


def _legend(report: Report) -> Iterator[str]:
    """What each mode is, once, rather than in every shell's table."""
    seen: list = []
    for entry in report.per_shell:
        for result in entry.modes:
            if result.mode.name not in [m.name for m in seen]:
                seen.append(result.mode)
    if not seen:
        return
    yield "What the modes are:"
    width = max(len(m.name) for m in seen)
    for mode in seen:
        yield f"  {mode.name.ljust(width)}  {mode.real_life}"
    yield ""


def _login(report: Report) -> Iterator[str]:
    """The question people actually have, answered on its own."""
    story = report.login
    if story is None:
        return
    yield f"A login session here starts {story.shell.name} ({story.chosen}). It reads:"
    if story.runs:
        yield "  " + " then ".join(report.display(n) for n in story.runs)
    else:
        yield f"  {NOTHING} -- no startup file in {report.home} runs when you log in"
    if not story.missing:
        yield ""
        return
    yield "It does not read:"
    width = max(len(report.display(m.name)) for m in story.missing)
    for item in story.missing:
        yield f"  {report.display(item.name).ljust(width)}  {item.reason}"
        if item.mention is not None:
            mention = item.mention
            yield (
                f"  {' ' * width}  except that {report.display(mention.source.name)}:"
                f"{mention.line} {mention.verb} it -- if that line runs, this one does too."
                " Text, not observed."
            )
    yield ""


def _skipped(report: Report) -> Iterator[str]:
    skipped = [s for s in report.shells if s.skipped]
    if not skipped:
        return
    yield "Not probed:"
    width = max(len(s.name) for s in skipped)
    for shell in skipped:
        yield f"  {shell.name.ljust(width)}  {shell.skipped}"
    yield ""


def text(report: Report, quiet: bool = False) -> str:
    if quiet:
        return "\n".join(f.line() for f in report.findings)

    lines: list[str] = []
    if not report.candidates:
        lines.append(f"No startup files in {report.home}. Nothing to say.")
        return "\n".join(lines)
    if not probeable(report.shells):
        lines.append("No shell on PATH could be probed. Nothing below is observed.")
        lines.append("")

    lines.extend(_login(report))
    lines.append(f"Every startup file in {report.home}, and what starts it.")
    lines.append("")
    lines.extend(_mode_rows(report))
    lines.extend(_skipped(report))
    lines.extend(_legend(report))

    if report.findings:
        lines.append("Never read, as things stand:")
        width = max(len(report.display(f.name)) for f in report.findings)
        for finding in report.findings:
            lines.append(f"  {report.display(finding.name).ljust(width)}  {finding.message}")
        lines.append("")

    if report.mentions:
        lines.append("Text, not observed -- whichrc does not run your files:")
        for mention in report.mentions:
            lines.append(
                f"  {report.display(mention.source.name)}:{mention.line}: "
                f"{mention.verb} {report.display(mention.target)}, which is listed above as "
                f"never read. If that line runs, it is not."
            )
            lines.append(f"      {mention.text}")
        lines.append("")

    for note in report.notes:
        lines.append(f"Note: {note}")
    if report.notes:
        lines.append("")

    count = len(report.findings)
    if count:
        noun = "file" if count == 1 else "files"
        lines.append(f"{count} startup {noun} nothing here reads.")
    else:
        lines.append("Every startup file here is read by something.")
    return "\n".join(lines)


def to_json(report: Report) -> str:
    payload = {
        "home": str(report.home),
        "shells": [
            {
                "name": s.name,
                "path": str(s.path),
                "version": s.version,
                "skipped": s.skipped,
            }
            for s in report.shells
        ],
        "observed": [
            {
                "shell": entry.shell.name,
                "modes": [
                    {
                        "mode": m.mode.name,
                        "real_life": m.mode.real_life,
                        "reads": list(m.read_now),
                        "rounds": [list(r) for r in m.rounds],
                        "unprobed": m.unprobed,
                    }
                    for m in entry.modes
                ],
            }
            for entry in report.per_shell
        ],
        "findings": [asdict(f) | {"line": f.line()} for f in report.findings],
        "mentions": [
            {
                "file": mention.source.name,
                "line": mention.line,
                "target": mention.target,
                "sourcing": mention.sourcing,
                "text": mention.text,
            }
            for mention in report.mentions
        ],
        "notes": report.notes,
    }
    return json.dumps(payload, indent=2)
