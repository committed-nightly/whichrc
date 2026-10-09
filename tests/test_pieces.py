"""Tests for the small parts: locating files, reading text, naming shells."""

from __future__ import annotations

from pathlib import Path

from whichrc import candidates, mentions, shells

from .conftest import write


def test_only_real_files_count(home: Path) -> None:
    write(home, ".bashrc")
    (home / ".zshrc").symlink_to(home / "nothing-here")
    (home / ".profile").mkdir()
    found = [c.name for c in candidates.find(home)]
    # A dangling symlink and a directory are both things the shell will not
    # read either, so calling them unread would be true for the wrong reason.
    assert found == [".bashrc"]


def test_a_symlink_to_a_real_file_counts(home: Path, tmp_path: Path) -> None:
    real = tmp_path / "dotfiles-repo-bashrc"
    real.write_text("alias ll='ls -la'\n")
    (home / ".bashrc").symlink_to(real)
    assert [c.name for c in candidates.find(home)] == [".bashrc"]


def test_every_family_name_resolves_to_its_family() -> None:
    for family, names in candidates.FAMILIES.items():
        for name in names:
            assert candidates.family_of(name) == family


def test_discover_names_the_shells_it_did_not_find() -> None:
    found = shells.discover(("bash", "definitely-not-a-shell"))
    missing = next(s for s in found if s.name == "definitely-not-a-shell")
    assert missing.skipped == "not installed on this machine"
    assert missing not in shells.probeable(found)


def test_the_same_binary_under_two_names_is_only_probed_once(
    tmp_path: Path, monkeypatch
) -> None:
    """The /bin/sh case: one binary, two names, one table."""
    real = tmp_path / "theshell"
    real.write_text("#!/bin/sh\nexit 0\n")
    real.chmod(0o755)
    (tmp_path / "alsotheshell").symlink_to(real)
    monkeypatch.setenv("PATH", str(tmp_path))

    found = shells.discover(("theshell", "alsotheshell"))
    assert len(shells.probeable(found)) == 1
    second = next(s for s in found if s.name == "alsotheshell")
    assert second.skipped is not None
    assert "the same binary as theshell" in second.skipped


def test_a_version_that_is_an_error_message_is_not_a_version(tmp_path: Path) -> None:
    fake = tmp_path / "grumpy"
    fake.write_text('#!/bin/sh\necho "grumpy: 0: Illegal option --" >&2\nexit 2\n')
    fake.chmod(0o755)
    # Nothing on stdout, so nothing to show -- better than printing the
    # complaint in the version column.
    assert shells.version_of(fake) == ""


# --- the text layer ------------------------------------------------------


def _candidate(home: Path, name: str, text: str) -> candidates.Candidate:
    return candidates.Candidate(name, write(home, name, text))


def test_a_sourcing_line_is_labelled_as_sourcing(home: Path) -> None:
    source = _candidate(home, ".bash_profile", "export EDITOR=vim\n. ~/.bashrc\n")
    found = mentions.scan([source], [".bashrc"])
    assert len(found) == 1
    assert found[0].line == 2
    assert found[0].sourcing is True
    assert found[0].verb == "sources"


def test_a_bare_mention_is_still_reported_but_not_as_sourcing(home: Path) -> None:
    source = _candidate(home, ".bash_profile", 'echo "remember to fix ~/.bashrc"\n')
    found = mentions.scan([source], [".bashrc"])
    assert found[0].sourcing is False
    assert found[0].verb == "mentions"


def test_a_commented_out_line_is_not_a_mention(home: Path) -> None:
    source = _candidate(home, ".bash_profile", "#. ~/.bashrc\n   # . ~/.bashrc\n")
    assert mentions.scan([source], [".bashrc"]) == []


def test_a_file_does_not_mention_itself(home: Path) -> None:
    source = _candidate(home, ".bashrc", 'echo "this is ~/.bashrc"\n')
    assert mentions.scan([source], [".bashrc"]) == []


def test_sourcing_inside_a_conditional_still_counts(home: Path) -> None:
    source = _candidate(home, ".bash_profile", '[ -f ~/.bashrc ] && . ~/.bashrc\n')
    found = mentions.scan([source], [".bashrc"])
    assert found[0].sourcing is True


def test_undecodable_bytes_do_not_stop_the_scan(home: Path) -> None:
    path = home / ".bash_profile"
    path.write_bytes(b"\xff\xfe not utf-8\n. ~/.bashrc\n")
    source = candidates.Candidate(".bash_profile", path)
    assert mentions.scan([source], [".bashrc"])[0].line == 2
