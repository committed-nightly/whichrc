# whichrc

Say which shell startup files your shell actually reads, and name the ones it
never will.

You have five or six dotfiles in your home directory. Some of them run when
you open a terminal, some when you `ssh` in, some when a cron job starts a
shell, and at least one of them has not run since you copied it off an old
laptop. Nothing tells you which is which. The aliases work locally and are
missing over ssh; the `PATH` line you added is in the file nobody reads.

```
$ whichrc
A login session here starts bash (SHELL=/bin/bash). It reads:
  ~/.bash_profile then ~/.bash_logout
It does not read:
  ~/.bashrc      bash reads it in interactive and command over ssh, but not here
  ~/.bash_login  only if ~/.bash_profile were gone
  ~/.profile     only if ~/.bash_profile and ~/.bash_login were gone
```

**whichrc does not run your startup files, and does not read them to work out
what they do.** It makes a throwaway home directory containing files with
*your file names* and one `printf` each, starts the real shell against that,
and reports which markers came back. The answer comes from the shell binary on
your machine, which is the only thing whose opinion counts.

## Install

```
pip install git+https://github.com/committed-nightly/whichrc
```

Python 3.10 or newer, no dependencies. It needs at least one shell on your
PATH, which you have.

## Usage

`whichrc` with no arguments asks about your own home directory.

There is an example home directory in `examples/`, laid out the way most
people's actually are, so everything below runs from a fresh clone:

```
$ HOME_DIR=$(examples/build.sh)
$ whichrc --home "$HOME_DIR"
A login session here starts bash (SHELL=/bin/bash). It reads:
  .bash_profile then .bash_logout
It does not read:
  .bashrc      bash reads it in interactive and command over ssh, but not here
  .bash_login  only if .bash_profile were gone
  .profile     only if .bash_profile and .bash_login were gone

Every startup file in /tmp/tmp.XXXX, and what starts it.

bash  /usr/bin/bash  (GNU bash, version 5.2.21(1)-release (x86_64-pc-linux-gnu))
  login interactive   .bash_profile then .bash_logout
  login               .bash_profile
  interactive         .bashrc
  command             nothing
  command over ssh    .bashrc
  as sh, login        .profile
  as sh, interactive  nothing

sh  /usr/bin/sh
  login interactive  .profile
  login              .profile
  interactive        nothing
  command            nothing
  command over ssh   nothing

Not probed:
  dash  the same binary as sh (/usr/bin/dash)
  zsh   not installed on this machine
  ksh   not installed on this machine
  mksh  not installed on this machine

What the modes are:
  login interactive   ssh you@host, or a login terminal; includes what runs on the way out
  login               su - you, or a display manager starting your session
  interactive         typing the shell's name in a terminal you already have
  command             shell -c '...', a Makefile recipe, a cron job
  command over ssh    ssh you@host 'some command' -- a command string, with a socket for stdin
  as sh, login        /bin/sh -l, on a machine where /bin/sh is this shell
  as sh, interactive  /bin/sh in a terminal

Never read, as things stand:
  .bash_login  bash would read it in login interactive only if .bash_profile were gone
  .zshrc       no shell here reads this name; zsh is not installed on this machine

2 startup files nothing here reads.
```

That output is from a machine with no zsh, and the last two lines say so. On a
machine that has zsh, `~/.zshrc` is read and is not a finding — which is the
whole point, and the reason the tool asks your shell rather than telling you
what shells do.

Exit status is 1 when there is a startup file nothing reads and 0 when there
isn't, so it works in a dotfiles repository's CI. `-q` prints just those
lines, with absolute paths, for grepping:

```
$ whichrc --home "$HOME_DIR" -q
/tmp/tmp.XXXX/.bash_login: shadowed: bash would read it in login interactive only if .bash_profile were gone
/tmp/tmp.XXXX/.zshrc: unread: no shell here reads this name; zsh is not installed on this machine
```

The two codes are the only things that affect the exit status:

- **`shadowed`** — the shell would read this file, but another one gets there
  first. A login shell reads the first of `~/.bash_profile`, `~/.bash_login`,
  `~/.profile` that exists, so creating the first one silently retires the
  other two.
- **`unread`** — no shell here reads that name in any mode, even with every
  other startup file deleted. Usually a file for a shell you no longer have.

Everything else is reported but not counted. `~/.bashrc` not running on
`ssh you@host` is the commonest surprise there is, and it is also a perfectly
deliberate arrangement, so it goes in the login section rather than being
called a fault.

Other flags: `--shell PATH` (repeatable) to probe particular shells instead of
searching PATH, `--json` for the full rounds, `--timeout SECONDS` if a shell
on your machine is slow to start.

## The one thing it can't see

whichrc never runs your files, so it cannot see a file your own config
sources. If `~/.bash_profile` ends in `. ~/.bashrc`, the probe still reports
`~/.bashrc` as unread by login shells, and that is the wrong answer for your
machine.

So it also reads the text of the files the shell does start, and offers any
line naming a file it just called unread — under a heading saying this part is
not observed. Put the usual two lines on the end of the example's
`~/.bash_profile`:

```
$ printf '\n[ -z "$PS1" ] && return\n. ~/.bashrc\n' >> "$HOME_DIR/.bash_profile"
$ whichrc --home "$HOME_DIR" | head -5
A login session here starts bash (SHELL=/bin/bash). It reads:
  .bash_profile then .bash_logout
It does not read:
  .bashrc      bash reads it in interactive and command over ssh, but not here
               except that .bash_profile:6 sources it -- if that line runs, this one does too. Text, not observed.
```

It does not decide whether the line runs — and this example is exactly why.
Line 5 is `[ -z "$PS1" ] && return`, so for a login shell that is *not*
interactive, line 6 is never reached and `~/.bashrc` really is unread. Which
of the two it is depends on how the shell was started, three lines of quoting,
and a variable the probe deliberately does not set. A tool that guessed would
be wrong exactly when it mattered.

## Why it probes instead of knowing

The rules are documented, and the documentation is not the machine. Two
examples from building this:

**`~/.bash_logout` is not read by a shell given `-c`.** The first version of
the probe started every shell as `shell -c :`, which is tidy and never runs
the logout file, because that one belongs to an interactive login shell
exiting normally. It reported `~/.bash_logout` — a file bash runs every single
time you log out — as a file nothing reads. The probe now hands the shell
`/dev/null` as stdin and no command, which is what a session looks like from
the shell's side.

**`ssh you@host 'cmd'` reads `~/.bashrc`, and the probe nearly said it
doesn't.** bash sources `~/.bashrc` for a non-interactive shell started by
sshd if `SSH_SOURCE_BASHRC` was defined when it was built, or if
`getpeername()` says its stdin is a network connection — but either way, only
when `SHLVL` says the shell is top-level. A probe inherits `SHLVL` from the
shell that ran it, so the first version of this got `nothing` for that row and
a confident paragraph here explaining that Ubuntu's bash must not be built
with `SSH_SOURCE_BASHRC`. It is. One variable, and the tool was wrong about
the mode whose answer people most want:

```
$ H=$(mktemp -d); echo 'echo bashrc ran' > "$H/.bashrc"

$ HOME=$H SSH_CLIENT="1.2.3.4 5 22" env -u SHLVL bash -c true
bashrc ran

$ HOME=$H SSH_CLIENT="1.2.3.4 5 22" SHLVL=1 bash -c true
$
```

The probe now drops `SHLVL`, because the shell sshd starts is top-level and so
is the one `login` starts. That row is also probed with a real loopback TCP
socket on stdin, since `SSH_CLIENT` in the environment alone does not satisfy
`getpeername()`. On a bash built without the option your machine will say
`nothing` there, and that will be the right answer for your machine, which is
the entire point.

That is also how shadowing is worked out. Rather than encode "the first of
these three wins", whichrc probes, deletes whatever got read, and probes
again, until a round reads nothing — the rounds *are* the precedence chain.
Then, because two files read in one round are not necessarily in one chain, it
puts each earlier file back one at a time to find out which of them actually
mattered. That is why the `.bash_login` line above blames `.bash_profile` and
not `.bash_logout`, which was read in the same round and had nothing to do
with it.

## Deliberately not done

- **System files.** `/etc/profile`, `/etc/bash.bashrc`, `/etc/zsh/*` and
  `/etc/profile.d/*` are read before yours and are not reported, because the
  method depends on being able to relocate a file into a sandbox and those
  paths are compiled into the shell. Everything whichrc says is about one home
  directory.
- **`BASH_ENV` and `ENV`.** These name a file for the shell to run and are
  scrubbed from the probe environment, because leaving them in would mean
  executing one of your real files. If either is set, whichrc says so and
  stops there.
- **`ZDOTDIR`.** zsh looks for its files in `$ZDOTDIR` when that is set.
  whichrc reports the variable and tells you to run
  `whichrc --home "$ZDOTDIR"`, rather than modelling the relocation.
- **csh and fish.** Different startup rules and, in fish's case, a different
  language; neither fits the `-l`/`-i` probe shape.

## Licence

MIT.
