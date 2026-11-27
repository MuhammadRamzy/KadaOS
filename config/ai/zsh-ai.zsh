# KadaOS AI in the terminal (sourced from ~/.zshrc)
#   ?? <what you want>   → suggests ONE command and puts it on your prompt to review/edit (never runs it)
#   ??! <what you want>  → same, but asks Claude (more accurate, slower)
#   why                  → explains why the last command failed (re-run it with output: cmd 2>&1 | why)
#   ai <question>        → answer in the terminal; can check your laptop live (read-only);  ai-search / fai search <query> → find files by meaning
_fai_cmd() { local c; c=$(fai cmd "$@") || return; [[ -n $c ]] || return; c=$(fai handoff -- "$c") || return; [[ -n $c ]] && print -z -- "$c"; }
_fai_cmd_claude() { local c; c=$(fai cmd --claude "$@") || return; [[ -n $c ]] || return; c=$(fai handoff -- "$c") || return; [[ -n $c ]] && print -z -- "$c"; }
alias '??'='noglob _fai_cmd'
alias '??!'='noglob _fai_cmd_claude'
alias ai='noglob fai sys'
_fai_project_root() { git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || print -r -- "$PWD"; }
aip() { local root; root=$(_fai_project_root) || return; fai rag --project "$root" "$@"; }
ais() { local root; root=$(_fai_project_root) || return; fai search --project "$root" "$@"; }
typeset -g _fai_last_cmd="" _fai_last_status=0
# Preserve the command being explained; preexec also runs before `why` itself.
_fai_preexec() { [[ $1 =~ '^[[:space:]]*why([[:space:]]|$)' ]] || _fai_last_cmd=$1 }
_fai_precmd() { _fai_last_status=$? }
autoload -Uz add-zsh-hook
add-zsh-hook preexec _fai_preexec
add-zsh-hook precmd _fai_precmd
why() {
  if [[ ! -t 0 ]]; then fai why "$@"; return; fi
  [[ $_fai_last_cmd == why* || -z $_fai_last_cmd ]] && { echo "Run it right after a failed command, or: cmd 2>&1 | why"; return 1; }
  local ans explanation suggestion; read -q "ans?Re-run \"$_fai_last_cmd\" to capture its error output? [y/N] "; echo
  if [[ $ans == y ]]; then
    explanation=$(eval "$_fai_last_cmd" 2>&1 | tail -60 | fai why --code "$_fai_last_status" -- "$_fai_last_cmd") || return
  else
    explanation=$(fai why --code "$_fai_last_status" -- "$_fai_last_cmd" </dev/null) || return
  fi
  print -r -- "$explanation"
  suggestion=$(print -r -- "$explanation" | fai handoff --answer) || return
  [[ -n $suggestion ]] && print -z -- "$suggestion"
}

# cat in a terminal: Markdown rendered (glow), code/config highlighted (bat). Pipes, redirects and options get the real cat.
cat() {
  if [[ -t 1 && $# -gt 0 && $1 != -* ]]; then
    local f md=1; for f in "$@"; do [[ -f $f && ${f:l} == *.(md|markdown) ]] || md=0; done
    if (( md && $+commands[glow] )); then
      for f in "$@"; do glow -s dark -w $(( COLUMNS > 110 ? 110 : COLUMNS - 2 )) -- "$f"; done; return
    fi
    if (( $+commands[bat] )); then bat --paging=never --style=plain -- "$@"; return; fi
  fi
  command cat "$@"
}
