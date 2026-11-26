# Reviewer brief template

Fill every `<…>`; the text around them goes in as written. One brief per agent's range. The reviewer sees nothing but this brief.

```
Repo: <absolute path of the worktree holding the head>; read only, edit nothing there.
Range: <base>..<head> on branch `<branch>`; review only this range (`git diff <base>..<head>`).
Spec: <issue link(s) and the checklist items this range claims, or the free-form outcomes as the user saw them>.
Mech proved: <the mech-review JSON for the head: summary line, each check's status, open entries verbatim>. A check that passed needs no second look; a skipped or partial one proved nothing.
Claims: <the equivalence claims and code removals the agent's report makes, verbatim>.
Focus: <the agent's focus areas from its review request>.

Standing rules, every review:
1. Validators: try malformed and degenerate input on every validator the range adds or changes (bad tokens, empty values, nesting, unbalanced pairs). Input that loads and then passes silently or crashes later is a finding.
2. Mutants: sample equivalence claims by applying the mutant. An "equivalent mutant" claim stands only if no input changes a result; one input that does makes it a finding.
3. Removed code: for any code the range removes (a cache, a branch, a check), above all under mutation pressure, compare behaviour and timing at base and head on the same input. Slower or different is a finding.
4. Expected values: CONFIRM or REJECT each changed expected value against a quoted spec sentence. No sentence sets it → REJECT. A spec-reversed removal (`removed, spec #N reverses it`): CONFIRM only against a quoted sentence of #N that reverses the removed test's assertion, else REJECT (restore the test). Any other test removal stays the owner's waiver.
5. Evidence: reproduce in a scratch copy at `<repo>/.claude/worktrees/<name>` (`git worktree add <that path> <head>`, then EnterWorktree with `path:` it; removed after), never in the repo above, and report each finding reproduced or plausible.

Report: one row per finding: file, line, failure scenario (input → wrong output), rule number or "other", reproduced or plausible, the command that shows it. None found → say so per rule, with what you tried.
```
