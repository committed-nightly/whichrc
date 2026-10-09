#!/bin/sh
# Build a throwaway home directory with the commonest shell setup there is,
# so the tool has something to look at. Prints the path it made.
#
#   whichrc --home "$(examples/build.sh)"
#
# Nothing here is wrong on purpose except by omission: ~/.bash_profile sets up
# a login shell and never sources ~/.bashrc, which is how half the world's
# dotfiles are arranged and why half the world's aliases are missing over ssh.
#
# ~/.bash_login and ~/.profile are both real files that a login bash will
# never open, because ~/.bash_profile exists and a login shell reads the first
# of the three that does. ~/.zshrc is left over from a machine that had zsh.
set -eu

home=${1:-$(mktemp -d)}
mkdir -p "$home"

cat > "$home/.bash_profile" <<'EOF'
# Login shells start here.
export EDITOR=vim
export PATH="$HOME/.local/bin:$PATH"
EOF

cat > "$home/.bash_login" <<'EOF'
# Added in 2019, in a hurry, and never read since.
export PATH="$HOME/go/bin:$PATH"
EOF

cat > "$home/.profile" <<'EOF'
# The portable one. /bin/sh still reads it.
export LANG=en_GB.UTF-8
EOF

cat > "$home/.bashrc" <<'EOF'
alias ll='ls -la'
alias gs='git status -sb'
export PS1='\w \$ '
EOF

cat > "$home/.bash_logout" <<'EOF'
clear
EOF

cat > "$home/.zshrc" <<'EOF'
# From the laptop before this one.
autoload -Uz compinit && compinit
EOF

printf '%s\n' "$home"
