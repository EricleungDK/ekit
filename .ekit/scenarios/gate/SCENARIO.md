# gate: Stop hook allows only on fresh PASS plus the finish report

- story: As a user with the kit installed, in a session started with /orchestrate-agent, Claude cannot stop on unverified work in a repo with scenarios, and can once scenarios are green.
- covers: #9 scenario per deliverable (Stop gate); the gate allows the stop after a fresh PASS and the finish report; a commit keeps the PASS fresh; subagent stops are not gated; a stop while a subagent still runs is a wait, not gated
- steps:
  1. Sample repo with passing scenario `ok`; cloud/install.sh; fire the installed SessionStart hook (records baseline).
  2. Edit without /orchestrate-agent -> Stop allows (gate is orchestrate-only); revert; fire the installed UserPromptSubmit hook with `/orchestrate-agent` (arms the gate).
  2b. Stop hook, no work done -> allow (no output).
  3. Edit a file; Stop hook -> block ("Scenarios not green"), naming the runner.
  3b. Same Stop with a running subagent in `background_tasks` -> allow (a wait); with the list empty -> block again.
  4. stop_hook_active=true -> allow (loop guard).
  5. Run the runner -> PASS; Stop hook with no finish report -> block, asking for `## Finish: done`.
  6. Edit, run -> PASS; Stop hook whose last message is the finish report -> allow (no output).
  7. Commit the reported tree; Stop hook -> allow (the PASS and the report still fit the tree).
  8. The installed settings register no SubagentStop gate.
- expected: block JSON `{"decision":"block"...}` only in steps 3, 3b (empty list) and 5.
- children: stale-after-edit, failing-scenario
