import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ["EKIT_SCENARIO_DIR"], "fixtures"))
from stacks import (B, H, FakeGitHub, R2, checkout_untouched, edit, entry_rows, eq, has, hasnt,  # noqa: E402
                    merge, problems, r3, save, shard, tested)

# 1. each mutants result names the stack and folder it ran for
api = [shard("api", k, 2) for k in (0, 1)]
web = [shard("web", 0, 2), shard("web", 1, 2, survive="replace > with == in f0")]
for leg, files, want in (("api", api, {"stack": "python", "project_dir": "api"}),
                         ("web", web, {"stack": "rust", "project_dir": "web"})):
    for k, f in enumerate(files):
        d = json.load(open(f))
        eq(f"{leg} shard {k}/2 stack field", d.get("stack"), want)
        eq(f"{leg} shard {k}/2 shard field", d.get("shard"), {"k": k, "n": 2, "max_mutants": 40})

# 2. each stack's shards merge apart: api pass 2/2, web fail with its one MISSED mutant; no CI entry
rc, mapi = merge("api", 2, list(enumerate(api)))
eq("api merge exit", rc, 0)
eq("api R3", r3(mapi), "pass")
eq("api tested", tested(mapi), "2/2")
eq("api entries", problems(mapi), [])
rc, mweb = merge("web", 2, list(enumerate(web)))
eq("web merge exit", rc, 1)
eq("web R3", r3(mweb), "fail")
eq("web tested", tested(mweb), "12/12")
eq("web entries", problems(mweb), ["MISSED mutant web/src/lib.rs:1:7: replace > with == in f0"])
# the same, merged without --project-dir: the stack alone is compared, still clean
rc, out = merge("api", 2, list(enumerate(api)), project_dir=False)
eq("api merge without --project-dir exit", rc, 0)
eq("api merge without --project-dir entries", problems(out), [])

# 3. crossed wiring: web's shard 1 downloaded into api's merge as its shard 1
rc, crossed = merge("api", 2, [(0, api[0]), (1, web[1])])
eq("crossed exit", rc, 1)
eq("crossed R3", r3(crossed), "fail")
eq("crossed: exactly one CI entry naming the stack and folder", problems(crossed),
   ["mutants shard 1/2 produced no result: result is for stack rust in web, not python in api"])
eq("crossed: web's MISSED mutant not counted", problems(crossed, "R3"), [])
eq("crossed: only api's own shard counted", tested(crossed), "1/1")
# the other way round: api's result in web's merge
rc, out = merge("web", 2, [(0, web[0]), (1, api[1])])
eq("crossed web exit", rc, 1)
eq("crossed web entries", problems(out),
   ["mutants shard 1/2 produced no result: result is for stack python in api, not rust in web"])

# 4. #42's shard checks still hold, per stack
rc, out = merge("api", 2, [(0, api[0]), (1, api[0])])
eq("dup index exit", rc, 1)
eq("dup index entry", problems(out), ["mutants shards do not match: shard 0/2 given 2 times (--envelope 0, 1); shard 1/2 missing"])
rc, out = merge("api", 2, [(0, api[0])])
eq("missing shard exit", rc, 1)
eq("missing shard entry", problems(out), ["mutants shard 1/2 produced no result: no result file given"])
cap5 = edit(api[1], "api-cap5.json", lambda d: d["shard"].update(max_mutants=5))
rc, out = merge("api", 2, [(0, api[0]), (1, cap5)])
eq("cap mismatch exit", rc, 1)
eq("cap mismatch entry", problems(out), ["mutants shards do not match: shards ran with different caps (max-mutants 5, 40)"])
old = edit(api[1], "api-oldhead.json", lambda d: d.update(head=B))
rc, out = merge("api", 2, [(0, api[0]), (1, old)])
eq("old head exit", rc, 1)
eq("old head entry", problems(out), [f"mutants shard 1/2 produced no result: result is for an older head, not {H}"])
ZERO = "0" * 40
otherbase = edit(api[1], "api-otherbase.json", lambda d: d.update(base=ZERO))
rc, out = merge("api", 2, [(0, api[0]), (1, otherbase)])
eq("base mismatch exit", rc, 1)
eq("base mismatch entries", len(problems(out)), 1)
has("base mismatch entry", problems(out)[0], f"mutants shards do not match: shard 1/2 ran on base {ZERO}")
# a foreign stack's shard with another cap and base is that stack's: it is named once and never trips api's #42 checks
foreign = edit(web[1], "web-cap5-otherbase.json", lambda d: (d["shard"].update(max_mutants=5), d.update(base=ZERO)))
rc, out = merge("api", 2, [(0, api[0]), (1, foreign)])
eq("foreign shard exit", rc, 1)
eq("foreign shard: one entry naming its stack, no shard mismatch", problems(out),
   ["mutants shard 1/2 produced no result: result is for stack rust in web, not python in api"])
# web's own shards still pass #42 while api's are broken
eq("web unaffected", problems(mweb, "CI"), [])

# 5. the report: one comment, a row per stack, each stack's R3 apart; the check fails on web's MISSED
gh = FakeGitHub()
try:
    clean_web = [shard("web", k, 2) for k in (0, 1)]
    rc, mweb_clean = merge("web", 2, list(enumerate(clean_web)))
    eq("web clean merge exit", rc, 0)
    MAPI, MWEB, MWEBC, MCROSS = (save(n, d) for n, d in (("m-api.json", mapi), ("m-web.json", mweb),
                                                       ("m-web-clean.json", mweb_clean), ("m-cross.json", crossed)))
    rows = lambda api_m, web_m: [("api", "python", "api", {"r2": R2["api"], "mutants": api_m}),  # noqa: E731
                                 ("web", "rust", "web", {"r2": R2["web"], "mutants": web_m})]
    rc, body = gh.report(rows(MAPI, MWEBC))
    eq("clean report exit (check passes)", rc, 0)
    has("clean: api row", body, "| api | python | api | pass ")
    has("clean: web row", body, "| web | rust | web | pass ")
    rc, body = gh.report(rows(MAPI, MWEB))
    eq("missed report exit (check fails)", rc, 1)
    has("api row passes", body, "| api | python | api | pass ")
    has("web row fails", body, "| web | rust | web | fail ")
    has("api R3 timing apart", body, "api: R3 timing: 2/2 mutants")
    has("web R3 timing apart", body, "web: R3 timing: 12/12 mutants")
    ents = entry_rows(body)
    eq("one R3 entry, web's", [(e["stack"], e["problem"]) for e in ents if e["id"].startswith("R3-")],
       [("web", "MISSED mutant web/src/lib.rs:1:7: replace > with == in f0")])
    # 6. the crossed-wiring entry reaches the comment, in api's row, and fails the check
    rc, body = gh.report(rows(MCROSS, MWEBC))
    eq("crossed report exit (check fails)", rc, 1)
    has("api row fails", body, "| api | python | api | fail ")
    has("web row still passes", body, "| web | rust | web | pass ")
    ci = [(e["stack"], e["severity"], e["problem"]) for e in entry_rows(body) if e["id"].startswith("CI-")]
    eq("crossed: one CI entry in the comment, api's", ci,
       [("api", "fail", "mutants shard 1/2 produced no result: result is for stack rust in web, not python in api")])
    hasnt("crossed: web's MISSED never shown", body, "MISSED mutant")
    hasnt("never all pass", body, "all pass")
finally:
    gh.close()

checkout_untouched()
print("mech-review-mutants/stacks ok")
