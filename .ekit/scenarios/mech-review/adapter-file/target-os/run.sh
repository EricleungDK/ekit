#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
# the install: a clone of the kit
KIT="$PWD/kit"; git -c advice.detachedHead=false clone -q "$EKIT_REPO" "$KIT" 2>/dev/null || fail "git clone of the kit failed"
MR="$KIT/scripts/mech-review.py"; TS="$KIT/scripts/mech_review/adapters/ts.toml"
R="$PWD/repo"; mkdir -p "$R/src" "$R/tests"; git -C "$R" init -q -b main
echo '{}' > "$R/package.json"; echo 'export const add = (a: number, b: number) => a + b;' > "$R/src/calc.ts"
printf 'import { add } from "../src/calc";\ndescribe("Calc", () => {\n  it("adds", () => { expect(add(1, 2)).toBe(3); });\n});\n' > "$R/tests/calc.test.ts"
git -C "$R" add -A; git -C "$R" commit -qm base; B=$(git -C "$R" rev-parse HEAD)
# resolve <label> <want exit> <args...>: as the workflow's stack job runs it; OUT, ERR
resolve() { local l=$1 want=$2; shift 2
  OUT=$(python3 -I "$MR" resolve --repo "$R" --base "$B" --head "$B" "$@" 2>err); local rc=$?; ERR=$(cat err)
  hasnt "$l traceback" "$ERR" "Traceback"; eq "$l exit" "$rc" "$want"; }
tos() { jq -r .target_os <<<"$OUT"; }
# variant <file> <target-os line>: the shipped ts.toml with that line after `manifests`
variant() { python3 -I -c 'import sys; s=open(sys.argv[1]).read(); i=s.index("\nmanifests"); j=s.index("\n", i+1)
open(sys.argv[2],"w").write(s[:j+1] + sys.argv[3] + "\n" + s[j+1:])' "$TS" "$1" "$2"; }

# 58.2: the built-in stacks are linux; an adapter file with no target-os reads linux
resolve auto 0; eq "auto: stack" "$(jq -r .stack <<<"$OUT")" ts; eq "auto: linux" "$(tos)" linux
for s in rust python ts; do resolve "built-in $s" 0 --stack "$s"; eq "built-in $s: linux" "$(tos)" linux; done
grep -q '^target-os' "$TS" && fail "the shipped ts.toml sets target-os; this step wants one without"
resolve "no target-os" 0 --stack ts --adapter "$TS"; eq "no target-os: linux" "$(tos)" linux

# 58.1 / 58.3: each valid value parses and is the output's
for os in linux macos windows; do
  variant "$os.toml" "target-os = \"$os\""
  resolve "$os" 0 --stack ts --adapter "$PWD/$os.toml"; eq "$os: target_os" "$(tos)" "$os"
  eq "$os: keys" "$(jq -c 'keys' <<<"$OUT")" '["error","project_dir","stack","target_os"]'
  # the file still describes R2: r2 through it runs
  r2=$(python3 -I "$MR" r2 --repo "$R" --base "$B" --head "$B" --stack ts --adapter "$PWD/$os.toml" --test-paths 'tests/**' 2>&1); rc=$?
  eq "$os: r2 exit" "$rc" 0; has "$os: r2 summary" "$r2" "pass $B"
done
# a relative path from the repo dir works too
cp macos.toml "$R/mac.toml"
OUT=$(cd "$R" && python3 -I "$MR" resolve --base "$B" --head "$B" --stack ts --adapter mac.toml 2>/dev/null); eq "relative path: macos" "$(tos)" macos

# 58.1 misuse: any other value is a usage error naming target-os, for resolve and for r2
n=0
for v in '"Linux"' '"MacOS"' '"win"' '"darwin"' '"ubuntu-latest"' '"linux "' '""' '1' 'true' '["linux"]'; do
  n=$((n+1)); variant "bad$n.toml" "target-os = $v"
  resolve "bad $v" 2 --stack ts --adapter "$PWD/bad$n.toml"
  eq "bad $v: stdout empty" "$OUT" ""
  has "bad $v: names the field" "$ERR" "adapter file $PWD/bad$n.toml: target-os"
  r2=$(python3 -I "$MR" r2 --repo "$R" --base "$B" --head "$B" --stack ts --adapter "$PWD/bad$n.toml" --test-paths 'tests/**' 2>err); rc=$?
  eq "r2 bad $v: exit" "$rc" 2; eq "r2 bad $v: stdout empty" "$r2" ""; has "r2 bad $v: names the field" "$(cat err)" "target-os"
done
# a misspelt key is not silently linux
variant typo.toml 'target_os = "windows"'
resolve "target_os typo" 2 --stack ts --adapter "$PWD/typo.toml"; has "typo: names the key" "$ERR" "target_os"
# --stack must name the file's stack
resolve "wrong stack" 2 --stack python --adapter "$PWD/macos.toml"; eq "wrong stack: stdout empty" "$OUT" ""
echo "mech-review/adapter-file/target-os ok"
