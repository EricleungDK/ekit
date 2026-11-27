#!/bin/bash
source "$EKIT_REPO/.ekit/scenarios/lib.sh"
MR="$EKIT_REPO/scripts/mech-review.py"
TS="$EKIT_REPO/scripts/mech_review/adapters/ts.toml"
cp "$EKIT_PARENT_DIR/fixtures/ktspec.toml" good.toml
R="$PWD/repo"; cp -R "$EKIT_PARENT_DIR/fixtures/base" "$R"; git -C "$R" init -q -b main; git -C "$R" add -A; git -C "$R" commit -qm base
BASE=$(git -C "$R" rev-parse HEAD)
sed -i 's/test("keeps"/xtest("keeps"/' "$R/tests/CalcTest.kt"; git -C "$R" commit -qam cheat; HEAD=$(git -C "$R" rev-parse HEAD)

# good file first: the cheat is a fail, so a malformed file read as valid would show as exit 1 or 0, never 2
out=$(python3 "$MR" r2 --repo "$R" --base "$BASE" --head "$HEAD" --stack ktspec --adapter good.toml --test-paths 'tests/**'); eq "good exit" $? 1
has "good names the cheat" "$out" "disabled with an x prefix"

# bad <label> <file> <stderr substring> [sub=r2] [stack=ktspec]: a usage error, nothing on stdout, no traceback
bad() { local o e rc
  o=$(python3 "$MR" "${4:-r2}" --repo "$R" --base "$BASE" --head "$HEAD" --stack "${5:-ktspec}" --adapter "$2" --test-paths 'tests/**' 2>err); rc=$?; e=$(cat err)
  eq "$1 exit" "$rc" 2; eq "$1 stdout" "$o" ""; hasnt "$1 traceback" "$e" "Traceback"; has "$1 message" "$e" "$3"; }
# mk <file> <sed expr>: good.toml edited
mk() { sed "$2" good.toml > "$1"; }

mk m-format.toml '/^format = /d';            bad "missing format" m-format.toml "adapter file m-format.toml: format: missing"
mk m-name.toml '/^name = "ktspec"/d';        bad "missing name" m-name.toml "adapter file m-name.toml: name: missing"
mk m-ext.toml '/^extensions = /d';           bad "missing extensions" m-ext.toml "extensions: missing"
mk m-cases.toml '/^cases = /d';              bad "missing tests.cases" m-cases.toml "tests.cases: missing"
mk m-style.toml '/^block_style = /d';        bad "missing lexer.block_style" m-style.toml "lexer.block_style: missing"
mk m-ops.toml '0,/^operands = /{/^operands = /d}'; bad "eq without operands" m-ops.toml "asserts.call[0].operands: missing"
mk w-format.toml 's/^format = 1/format = "1"/';   bad "format a string" w-format.toml "format: \`1\`: want 1"
mk w-format2.toml 's/^format = 1/format = 2/';    bad "format 2" w-format2.toml "format: \`2\`: want 1"
mk w-ext.toml 's/^extensions = .*/extensions = ".kt"/'; bad "extensions a string" w-ext.toml "extensions: want a list of non-empty strings"
mk w-cases.toml 's/^cases = .*/cases = []/';      bad "cases empty" w-cases.toml "tests.cases: want at least one entry"
mk w-cases2.toml 's/^cases = .*/cases = [1, 2]/'; bad "cases ints" w-cases2.toml "tests.cases: want a list of non-empty strings"
mk w-min.toml 's/^separator = .*/&\nmin_args = true/'; bad "min_args a bool" w-min.toml "tests.min_args: want a whole number >= 0"
mk w-indent.toml 's/^block_style = .*/block_style = "indent"/'; bad "block_style indent" w-indent.toml "lexer.block_style: \`indent\` is not supported yet: want braces"
mk w-curly.toml 's/^block_style = .*/block_style = "curly"/';   bad "block_style unknown" w-curly.toml "lexer.block_style: unknown block style \`curly\`"
mk w-paren.toml 's/^brackets = .*/brackets = ["[]", "{}"]/';   bad "brackets without ()" w-paren.toml "lexer.brackets: want \"()\""
mk w-kind.toml '0,/^kind = "eq"/s//kind = "equal"/';           bad "assert kind" w-kind.toml "asserts.call[0].kind: \`equal\`: want eq, ne or other"
mk w-covers.toml 's/"ktlint-disable" = "file"/"ktlint-disable" = "block"/'; bad "covers value" w-covers.toml "suppressions[0].covers.ktlint-disable: \`block\`: want line, next-line or file"
mk w-tpl.toml 's/^skipped_text = .*/skipped_text = "test {nme} off"/';  bad "template field" w-tpl.toml "tests.skipped_text: unknown placeholder \`{nme}\`"
mk w-tpl2.toml 's/^skipped_text = .*/skipped_text = "test {name!r} off"/'; bad "template conversion" w-tpl2.toml "tests.skipped_text:"
mk w-skip.toml 's/^skip = .*/skip = ["nothere"]/'; bad "skip not a case" w-skip.toml "tests.skip[0]: \`nothere\` is not in tests.groups or tests.cases"
mk w-shape.toml 's/^shapes = .*/shapes = ["fun ID (...) ...{...}"]/'; bad "shape without NAME" w-shape.toml "functions.shapes[0]:"
mk w-esc.toml "0,/^escape = /s/^escape = .*/escape = 'ab'/"; bad "escape two chars" w-esc.toml "lexer.strings[1].escape: want one character"
mk w-name.toml 's/^name = "ktspec"/name = "kt spec"/'; bad "name with a space" w-name.toml "name: \`kt spec\`"
mk u-top.toml '1i colour = "red"';                    bad "unknown top key" u-top.toml "adapter file u-top.toml: colour: unknown key"
mk u-cases.toml 's/^cases = /casse = /';              bad "misspelt key" u-cases.toml "tests.casse: unknown key"
mk u-table.toml '$a [nonsense]\na = 1';               bad "unknown table" u-table.toml "nonsense: unknown key"
: > empty.toml;                                       bad "empty file" empty.toml "adapter file empty.toml: format: missing"
printf 'this is = = not toml [[\n' > nt.toml;         bad "not TOML" nt.toml "adapter file nt.toml: not valid TOML"
printf '\xff\xfe\x00bad' > bin.toml;                  bad "not UTF-8" bin.toml "adapter file bin.toml: not valid TOML"
mkdir adir;                                           bad "a directory" adir "adapter file adir: cannot read"
bad "a missing path" nope.toml "adapter file nope.toml: cannot read"
bad "stack not the file's name" good.toml "describes stack \`ktspec\`, not \`ts\`" r2 ts
bad "stack case differs" good.toml "describes stack \`ktspec\`, not \`KtSpec\`" r2 KtSpec
# #19 and #17 let mutants, baseline and plan take a file; merge reads no tree, so --adapter stays a usage error there
bad "merge with --adapter" "$TS" "--adapter applies to r2, red, all, mutants, baseline and plan (merge reads no tree)" merge ts
for sc in mutants baseline plan; do
  o=$(python3 "$MR" "$sc" --repo "$R" --base "$BASE" --head "$HEAD" --stack ts --adapter "$TS" --test-paths 'tests/**' 2>err); rc=$?
  eq "$sc with --adapter exit" "$rc" 0; hasnt "$sc with --adapter no usage error" "$(cat err)" "--adapter applies"
done
# #18: red and all run R1 and R4 through a file's [run]; a file without [run] is still r2 only for them
for sc in red all; do bad "$sc with an r2-only file" good.toml "--adapter applies to r2 only for good.toml: it has no [run] table" "$sc"; done
# a name that is not built in needs --adapter
o=$(python3 "$MR" r2 --repo "$R" --base "$BASE" --head "$HEAD" --stack ktspec --test-paths 'tests/**' 2>err); eq "unknown stack exit" $? 2
eq "unknown stack stdout" "$o" ""; has "unknown stack message" "$(cat err)" "--stack"

# odd but valid: a CRLF adapter file, a path relative to another cwd
sed 's/$/\r/' good.toml > crlf.toml
o=$(python3 "$MR" r2 --repo "$R" --base "$BASE" --head "$HEAD" --stack ktspec --adapter crlf.toml --test-paths 'tests/**'); eq "crlf exit" $? 1
has "crlf names the cheat" "$o" "test \`Calc / keeps\` disabled with an x prefix"
mkdir sub; o=$(cd sub && python3 "$MR" r2 --repo "$R" --base "$BASE" --head "$HEAD" --stack ktspec --adapter ../good.toml --test-paths 'tests/**'); eq "relative path exit" $? 1
echo "mech-review adapter-file malformed ok"
