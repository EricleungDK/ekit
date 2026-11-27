#!/bin/bash
# The grader support's trigger: evals/run.sh installs this file as `git` first on PATH, so the agent under test and
# every tool it starts run git through it. It runs the real git (the next `git` on PATH) with the same arguments,
# stdin, stdout, stderr and exit status. When the repo that command read holds a case's verdict script
# (<git common dir>/ekit-eval/verdict.py, written by the scaffold) and a ref or a worktree's HEAD moved (commit, reset,
# checkout, merge, rebase, stash, branch, worktree add, in any worktree) since that script last ran, it then runs it,
# silently, from the main checkout. It stands in for the scaffold's git hooks: the eval's Bash sandbox turns every git hook off
# (core.hooksPath=/dev/null and hook.<name>.enabled=false at command-line scope, through GIT_CONFIG_COUNT), so no
# hook runs there. Git run by the verdict script, and by the kit it calls, goes straight to the real git.
# A known limit: a ref moved past the shim (git run by its absolute path, or with a PATH that puts another git first; a
# ref file written by hand) is graded at the next git command through it; with none after it, the verdict stays the
# last one written (as a commit with the hooks bypassed did).
self="$(cd "$(dirname "$0")" && pwd -P)/$(basename "$0")"
real=
IFS=: && set -f && dirs=($PATH) && set +f && unset IFS  # no here-string: no temp file
for d in "${dirs[@]}"; do
  [ -n "$d" ] && [ -x "$d/git" ] && [ ! -d "$d/git" ] || continue
  [ "$d/git" -ef "$self" ] && continue
  real="$d/git" && break
done
[ -n "$real" ] || { echo "git: no git on PATH besides the ekit eval shim ($self)" >&2; exit 127; }
[ -z "${EKIT_EVAL_VERDICT_RUNNING:-}" ] || exec "$real" "$@"
# the leading global options, so the probes read the repo the command reads (-C, --git-dir, ...)
g=()
args=("$@")
i=0
while [ "$i" -lt "${#args[@]}" ]; do
  case ${args[i]} in
    -C | -c | --git-dir | --work-tree | --namespace | --config-env | --super-prefix)
      [ $((i + 1)) -lt "${#args[@]}" ] || break
      g+=("${args[i]}" "${args[i + 1]}"); i=$((i + 2)) ;;
    --*=* | -p | -P | --paginate | --no-pager | --bare | --no-replace-objects | --no-lazy-fetch | --no-optional-locks \
      | --literal-pathspecs | --glob-pathspecs | --noglob-pathspecs | --icase-pathspecs | --no-advice)
      g+=("${args[i]}"); i=$((i + 1)) ;;
    *) break ;;
  esac
done
common="$("$real" "${g[@]}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null </dev/null)"
[ -n "$common" ] && [ -f "$common/ekit-eval/verdict.py" ] || exec "$real" "$@"
state() {
  "$real" "${g[@]}" for-each-ref --format='%(refname) %(objectname)' 2>/dev/null </dev/null
  "$real" "${g[@]}" worktree list --porcelain 2>/dev/null </dev/null
  "$real" "${g[@]}" reflog show --all --format=%H 2>/dev/null </dev/null  # a ref moved and back in one command
}
"$real" "$@"
rc=$?
# against the state the last verdict saw (.git/ekit-eval/state), not the one before this command: a ref moved by a
# command that went past the shim (or by hand) is graded at the next git command through it
if [ "$(state)" != "$(cat "$common/ekit-eval/state" 2>/dev/null)" ]; then
  (cd "$(dirname "$common")" && EKIT_EVAL_VERDICT_RUNNING=1 python3 -I "$common/ekit-eval/verdict.py") \
    >/dev/null 2>&1 </dev/null
  printf '%s' "$(state)" > "$common/ekit-eval/state" 2>/dev/null
fi
exit "$rc"
