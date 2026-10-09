"""whichrc's command line."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import analyse, report
from .probe import DEFAULT_TIMEOUT

#: Exit 1 means "found startup files nothing reads", like a linter. Exit 2 is
#: argparse's, i.e. you typed it wrong.
EXIT_FINDINGS = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whichrc",
        description=(
            "Say which shell startup files your shell actually reads, and name "
            "the ones it never will. Your files are not run: whichrc puts your "
            "file names in a throwaway home directory with contents of its own "
            "and starts the real shell against that."
        ),
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=Path(os.path.expanduser("~")),
        metavar="DIR",
        help="the home directory to ask about (default: your own)",
    )
    parser.add_argument(
        "--shell",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="probe this shell instead of searching PATH; repeatable",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=f"how long one probe may take (default: {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="print the findings only, one per line, nothing else",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = args.home.expanduser()
    if not home.is_dir():
        print(f"whichrc: {home} is not a directory", file=sys.stderr)
        return 2

    result = analyse.run(home, shell_paths=args.shell, timeout=args.timeout)
    out = report.to_json(result) if args.json else report.text(result, quiet=args.quiet)
    if out:
        print(out)
    return EXIT_FINDINGS if result.findings else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
