---
type: llm
weight: 1
---

Pass only if every entry whose `class` is `adapter-fix` (`R0-00e0bfc4`, `R0-6d261a04`, `D-7e776699`, `CI-599b7f05`, `CI-f2f3b6a8`) gets an evidence line with the label `adapter-fix`, verbatim, e.g. `R0-6d261a04 → adapter-fix: entry .ekit/adapters/maven.toml:0, ...`, and none of them is labelled `real bug`, `Needs-you`, `flaky` or `sandbox/env`. `R2-0734ae9c` (`agent-fixable`, marked `blocked: R0`) opens with the `held` token instead, e.g. `R2-0734ae9c → held: blocked by R0-6d261a04`, never `adapter-fix` or `real bug`.
