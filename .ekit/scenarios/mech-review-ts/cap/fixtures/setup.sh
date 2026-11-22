# shared setup for the ts cap scenarios (sourced after lib.sh; not a scenario). cwd = the scenario's temp dir.
# The kit as a user gets it (a clone); a Stryker install outside the repo, as the workflow makes one
# (`npm install --prefix $RUNNER_TEMP/stryker`): node_modules/.bin/stryker -> @stryker-mutator/core, with
# @stryker-mutator/instrumenter beside it. Both are fakes (fixtures/stryker.mjs, fixtures/instrumenter.mjs) that
# answer from table.json: 14 mutants, one risk class per line, on two changed files.
command -v node >/dev/null || fail "node not on PATH: the ts cap needs node to list the mutants"
CAPFX="$EKIT_REPO/.ekit/scenarios/mech-review-ts/cap/fixtures"
git -C "$EKIT_REPO" diff HEAD --quiet -- scripts || fail "the kit has uncommitted changes under scripts/: commit them, then run again"
KIT="$PWD/kit"; git clone -q "$EKIT_REPO" "$KIT" || fail "git clone of the kit failed"
MR="$KIT/scripts/mech-review.py"

SI="$PWD/stryker"; NM="$SI/node_modules/@stryker-mutator"
mkdir -p "$NM/core/bin" "$NM/instrumenter" "$SI/node_modules/.bin"
printf '{"name":"@stryker-mutator/core","version":"10.0.0","type":"module","bin":{"stryker":"bin/stryker.js"}}\n' > "$NM/core/package.json"
printf '{"name":"@stryker-mutator/instrumenter","version":"10.0.0","type":"module","main":"index.js"}\n' > "$NM/instrumenter/package.json"
cp "$CAPFX/stryker.mjs" "$NM/core/bin/stryker.js"; chmod +x "$NM/core/bin/stryker.js"
cp "$CAPFX/instrumenter.mjs" "$NM/instrumenter/index.js"
ln -s ../@stryker-mutator/core/bin/stryker.js "$SI/node_modules/.bin/stryker"
STRYKER="$SI/node_modules/.bin/stryker"
export FAKE_TABLE="$CAPFX/table.json"

# the user's repo: base has the two files with one line each; head rewrites both (every line changed)
R="$PWD/repo"; mkdir -p "$R/src" "$R/tests" "$R/node_modules/.bin"; git -C "$R" init -q -b main
printf 'node_modules/\n' > "$R/.gitignore"
printf '{"name":"grade","devDependencies":{"vitest":"5.0.5"}}\n' > "$R/package.json"
printf '#!/bin/bash\necho 5.0.5\n' > "$R/node_modules/.bin/vitest"; chmod +x "$R/node_modules/.bin/vitest"
printf 'export const grade = 1;\n' > "$R/src/grade.ts"
printf 'export const util = 1;\n' > "$R/src/util.ts"
printf 'import { it, expect } from "vitest";\nimport { grade } from "../src/grade";\n\nit("grades", () => {\n  expect(grade(11, [1])).toBe("pts");\n});\n' > "$R/tests/grade.test.ts"
git -C "$R" add -A; git -C "$R" commit -qm base; B=$(git -C "$R" rev-parse HEAD)
cat > "$R/src/grade.ts" <<'TS'
export function grade(n: number, xs: number[]): string {
  const unit = "pts";
  let total = n * 2;
  log(total);
  const ok = true;
  if (n > 10) {
    return unit;
  }
  const pick = xs.filter((x) => x > 0);
  const any = ok && pick.length;
  const next = total++;
  const empty = [];
  return !ok ? "neg" : unit;
}
TS
cat > "$R/src/util.ts" <<'TS'
export function util(s: string): string {
  if (s.length) return s;
  return "none";
}
TS
git -C "$R" add -A; git -C "$R" commit -qm head; H=$(git -C "$R" rev-parse HEAD)

mut() { python3 -I "$MR" mutants --repo "$R" --base "$B" --head "$H" --stack ts --test-paths 'tests/**' --mutants-cmd "$STRYKER" "$@"; }
bl() { python3 -I "$MR" baseline --repo "$R" --base "$B" --head "$H" --stack ts --test-paths 'tests/**' --mutants-cmd "$STRYKER" "$@"; }
mrg() { python3 -I "$MR" merge --repo "$R" --base "$B" --head "$H" --stack ts "$@"; }
r3() { jq -r .checks.R3.status <<<"$1"; }
note() { jq -r .checks.R3.note <<<"$1"; }
nmissed() { jq -r '[.entries[] | select(.check=="R3" and (.problem | startswith("MISSED")))] | length' <<<"$1"; }
# the changed lines a run's --mutate ranges cover, as `file:line` sorted and joined by spaces: lines_of <argv line>
lines_of() { sed -n 's/.*--mutate \([^ ]*\).*/\1/p' <<<"$1" | tr ',' '\n' | while IFS= read -r g; do
    f=${g%:*}; a=${g##*:}; b=${a#*-}; a=${a%-*}; for ((i = a; i <= b; i++)); do echo "$f:$i"; done; done | sort -t: -k1,1 -k2,2n | tr '\n' ' ' | sed 's/ $//'; }
