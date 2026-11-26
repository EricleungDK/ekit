---
type: llm
# a claim only the trace shows: what the written workflow holds (its path is the agent's choice; setup.md step 6). A
# known limit: the judge's view of a long trace drops its middle, which may hold that write
focus: trace
weight: 1
---

Judge the trace. Find the base CI workflow the agent wrote under `.github/workflows/` (a Write, Edit or shell command; the job that is not the mech-review caller), as it was last written. Pass only if it runs the adapter's own commands (install, build, lint, test from the adapter file's `[commands]`, in that order, an empty one left out), on the target OS's runner (`ubuntu-latest` for linux), with no step the adapter does not name beside checking out the code and setting up the toolchain.
