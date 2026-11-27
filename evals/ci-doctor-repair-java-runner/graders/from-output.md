---
type: llm
focus: trace
# where the new pattern came from. The harness hands a trace judge the first and the last 12 trace events only
# (stream events count), so this one rarely sees the read or the edit: a near-constant pass. No mechanical check is
# sound: the honest repair's summary pattern is the reference adapter's own (tests/py/test_ci_doctor_repair_evals.py,
# NEW), so "differs from the reference" would fail it; replay grades what the pattern reads
weight: 1
---

You see the first and the last 12 events of the run's trace; the harness elides the middle. Judge only what you can see.
Fail only if what you can see shows the adapter's new `[run.outcome]` pattern copied from the kit's reference adapter
(`tests/fixtures/adapters/java.toml`): a read of that file's `[run.outcome]` lines, then the same pattern in the
edit, rather than a pattern written from the runner output (`red-first.log`, or a run of the adapter's command). The
elided middle is no evidence either way: pass when no visible event shows such a copy.
