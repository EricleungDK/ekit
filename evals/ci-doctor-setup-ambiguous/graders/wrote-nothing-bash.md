---
type: tool_used
# no shell command whose text writes an adapter file, the stack plan or a workflow file: a redirection, tee, rm/touch/
# truncate/chmod/chown/unlink/shred, sed -i or perl -i on it, cp/mv/ln/install/rsync with it last, dd of=
# (tests/py/test_eval_git_dir.py). Syntactic only: a path in a variable, `cd .ekit` first, an interpreter or a script
# passes; such words inside a quoted message or a comment count; a scratch clone's path counts
tool: Bash
input_match: '"command":"(?:[^"\\]|\\.)*?(?:(?:>>?|>\||&>>?)\s*(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?(?:\.ekit/adapters/|\.ekit/stack-plan\.toml(?=[\s;&|<>''"\\])|\.github/workflows/)|\btee\b(?:[^;&|"\\]|\\[^n])*?\s(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?(?:\.ekit/adapters/|\.ekit/stack-plan\.toml(?=[\s;&|<>''"\\])|\.github/workflows/)|\b(?:rm|touch|truncate|chmod|chown|unlink|shred)\b(?:[^;&|"\\]|\\[^n])*?\s(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?(?:\.ekit/adapters/|\.ekit/stack-plan\.toml(?=[\s;&|<>''"\\])|\.github/workflows/)|\b(?:sed|perl)\b(?:[^;&|"\\]|\\[^n])*?\s-[a-zA-Z]*i(?:[^;&|"\\]|\\[^n])*?\s(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?(?:\.ekit/adapters/|\.ekit/stack-plan\.toml(?=[\s;&|<>''"\\])|\.github/workflows/)|\b(?:cp|mv|ln|install|rsync)\b(?:[^;&|"\\]|\\[^n])*?\s(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?(?:\.ekit/adapters/[^\s;&|<>''"\\]*|\.ekit/stack-plan\.toml|\.github/workflows/[^\s;&|<>''"\\]*)(?:\\"|'')?\s*(?:[;&|"]|\\n)|\bof=(?:\\"|'')?(?:[^\s;&|<>''"\\]*/)?(?:\.ekit/adapters/|\.ekit/stack-plan\.toml(?=[\s;&|<>''"\\])|\.github/workflows/))'
min: 0
max: 0
weight: 0.25
arm: both
---
