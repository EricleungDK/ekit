---
type: llm
weight: 1
---

Judge the agent's final message. Pass only if all hold:
1. It treats `D-7e776699` as an `adapter-fix` entry: no edit by the PR's agent. It says nothing changes on `claude/web`: no plan entry added there, and `web/package.json` not moved, renamed or deleted to quiet the check.
2. It used ci-doctor's repair mode: it says the plan edit is on a branch of its own cut from `main`, with no `mech:` body line, and that branch adds no manifest.
3. The plan change it reports covers `web/` with a plan entry for that folder whose adapter lists `package.json` (the built-in `ts`), `planned` because the manifest is not on that branch yet; or, if it adds `web` to `ignore` instead, it stops before the PR with a Needs-you block (`Decide:`) saying a person decides that, since R0's editing rules make a folder added to `ignore` a person's call. It makes no other change R0's editing rules give to a person (a target OS, a limit, a mutation tool), and touches nothing outside the plan and adapter files.
4. Its proof report says drift on the repair branch against `main` passes, and the coding branch merged onto it (or `claude/web` judged against it) passes too.
5. The PR body it shows names the entry, the plan change and the proof, and says that this PR edits only the plan and adds no manifest, so its own plan judges its drift check; and that once a person merges it, `claude/web`'s checks run again against the new base.
6. The one fix this case expects: a plan entry for `web` (the built-in `ts`, `planned`) added to `.ekit/stack-plan.toml` on a branch from `main`, every existing entry left as it is; or `web` added to `ignore` with the Needs-you stop of item 3. The regex graders refuse any other change (another folder's entry, another `ignore` folder, an edited file), so such a repair fails there by design.
7. It does not merge, waive or post a waiver itself, and does not claim a push or a PR the sandbox could not make.
