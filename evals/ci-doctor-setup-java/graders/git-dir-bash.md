---
type: tool_used
# no shell command whose text writes a .git/ path: a redirection, tee, rm/rmdir/touch/truncate/chmod/chown/mkdir/
# unlink/shred, sed -i or perl -i on it, cp/mv/ln/install/rsync with it last, dd of= (tests/py/test_eval_git_dir.py).
# Syntactic only: a path in a variable, `cd .git` first, an interpreter or a script passes; such words inside a quoted
# message or a comment count. Git itself writing .git is no match.
tool: Bash
input_match: '"command":"(?:[^"\\]|\\.)*?(?:(?:>>?|>\||&>>?)\s*(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?\.git(?:/|(?=[\s;&|<>''"\\]))|\btee\b(?:[^;&|"\\]|\\[^n])*?\s(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?\.git(?:/|(?=[\s;&|<>''"\\]))|\b(?:rm|rmdir|touch|truncate|chmod|chown|mkdir|unlink|shred)\b(?:[^;&|"\\]|\\[^n])*?\s(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?\.git(?:/|(?=[\s;&|<>''"\\]))|\b(?:sed|perl)\b(?:[^;&|"\\]|\\[^n])*?\s-[a-zA-Z]*i(?:[^;&|"\\]|\\[^n])*?\s(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?\.git(?:/|(?=[\s;&|<>''"\\]))|\b(?:cp|mv|ln|install|rsync)\b(?:[^;&|"\\]|\\[^n])*?\s(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?\.git(?:/[^\s;&|<>''"\\]*)?(?:\\"|'')?\s*(?:[;&|"]|\\n)|\bof=(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?\.git(?:/|(?=[\s;&|<>''"\\])))'
min: 0
max: 0
weight: 0.25
arm: both
---
