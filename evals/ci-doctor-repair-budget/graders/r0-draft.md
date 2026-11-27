---
type: tool_used
tool: Bash
# a proof round ran: R0's static half on an adapter file (`--adapter`), whatever limit the CI doc names; the kit's own
# reference adapters (tests/fixtures/adapters/) do not count. A known limit: the team's adapter is on main, and a draft
# edited in place has its path, so a run of R0 on the unedited .ekit/adapters/go.toml also matches; no pattern over the
# command can tell the two apart
input_match: 'mech-review\.py[\s\S]*\br0\b[\s\S]*--adapter(?:=|\s+)(?:\\"|'')?(?![^\s"]*tests/fixtures/adapters/)'
arm: both
---
