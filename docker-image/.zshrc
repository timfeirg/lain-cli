ZSH_THEME="ys"
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export ZSH=$HOME/.oh-my-zsh
export EDITOR=vim
plugins=(
git
gitfast
git-extras
fasd
redis-cli
docker
pip
kubectl
)
source $ZSH/oh-my-zsh.sh

export ZLE_RPROMPT_INDENT=0

# smartcase behavior in tab completions, see https://www.reddit.com/r/zsh/comments/4aq8ja/is_it_possible_to_enable_smartcase_tab_completion/
zstyle ':completion:*' matcher-list 'm:{[:lower:]}={[:upper:]}'

COMPLETION_WAITING_DOTS="true"

# User configuration
DEBIAN_PREVENT_KEYBOARD_CHANGES=yes

export PATH="$GOPATH/bin:$HOME/.rvm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/X11/bin"
alias v='f -e vim'
# ansible related
alias ave="ansible-vault edit"

# edit all files that match this ag search
function agvi() {
  ag $@ -l | xargs -o vi
}

# vi mode
bindkey -v
bindkey '^h' backward-delete-char
bindkey '^w' backward-kill-word
bindkey '^[[Z' reverse-menu-complete
bindkey '^E' end-of-line
bindkey '^A' beginning-of-line
bindkey '^R' history-incremental-search-backward
export KEYTIMEOUT=1

# history config
HISTSIZE=100000
SAVEHIST=10000000
setopt menu_complete
setopt BANG_HIST
setopt HIST_IGNORE_ALL_DUPS
setopt HIST_FIND_NO_DUPS
setopt HIST_SAVE_NO_DUPS
setopt HIST_REDUCE_BLANKS

autoload -U compinit
compinit
zstyle ':completion:*:descriptions' format '%U%B%d%b%u'
zstyle ':completion:*:warnings' format '%BSorry, no matches for: %d%b'
setopt correctall

autoload -U promptinit
promptinit
alias gst='git branch --all && grv && git status --show-stash && git rev-list --format=%B --max-count=1 HEAD'
alias gfa='git fetch --all --tags --prune && git delete-merged-branches'
alias gcne='gc! --no-edit'
alias gcane='gca! --no-edit'
alias gcanep='gca! --no-edit && gp -f $1 $2'
alias gcls='gcl --depth 1 '
alias gcnep='gc! --no-edit && gp -f $1 $2'
alias grhd='git reset HEAD '
alias gcl='hub clone'
alias gcaanep='ga -A && gca! --no-edit && gp -f $1 $2'
alias glt='git log --decorate=full --simplify-by-decoration'
alias vi=$EDITOR
alias ssh='TERM=xterm ssh'

unsetopt correct_all
unsetopt correct
DISABLE_CORRECTION="true"

echo "
================================================================================
welcome to lain container, below are some tips.

* to manage mysql, copy the right mysql command from 1password, then run:
mysql -h[HOST] -uroot -p[PASSWORD]
================================================================================
"
