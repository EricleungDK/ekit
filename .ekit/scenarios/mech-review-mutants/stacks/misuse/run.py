import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "stacks", os.path.join(os.environ["EKIT_PARENT_DIR"], "fixtures", "stacks.py"))
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)
FakeGitHub = lib.FakeGitHub
R2 = lib.R2
checkout_untouched = lib.checkout_untouched
edit = lib.edit
entry_rows = lib.entry_rows
eq = lib.eq
has = lib.has
hasnt = lib.hasnt
merge = lib.merge
problems = lib.problems
r3 = lib.r3
save = lib.save
shard = lib.shard
count_tested = lib.count_tested

api = [shard("api", 0, 2), shard("api", 1, 2, survive="f2")]
web = [shard("web", k, 2) for k in (0, 1)]
rc, out = merge("api", 2, list(enumerate(api)))
eq("api with its survivor: exit", rc, 1)
MISSED = "MISSED mutant api/src/calc/core.py:6: return n + 2 -> return n - 2"
eq("api with its survivor: the MISSED entry", problems(out), [MISSED])

# 1. a result with no stack field, or a malformed one, is named and never counted (its MISSED mutant neither)
BAD = [
    ("nostack", lambda d: d.pop("stack"), "result has no stack field"),
    ("null", lambda d: d.update(stack=None), "result has a malformed stack field"),
    ("string", lambda d: d.update(stack="python"), "result has a malformed stack field \"python\""),
    ("list", lambda d: d.update(stack=["python", "api"]), "result has a malformed stack field"),
    ("empty-stack", lambda d: d.update(stack={"stack": "", "project_dir": "api"}), "result has a malformed stack field"),
    ("no-dir", lambda d: d.update(stack={"stack": "python"}), "result has a malformed stack field"),
    ("empty-dir", lambda d: d.update(stack={"stack": "python", "project_dir": ""}), "result has a malformed stack field"),
    ("dir-number", lambda d: d.update(stack={"stack": "python", "project_dir": 1}), "result has a malformed stack field"),
    ("empty-object", lambda d: d.update(stack={}), "result has a malformed stack field"),
]
for name, fn, want in BAD:
    f = edit(api[1], f"api-1-{name}.json", fn)
    for pd in (True, False):
        what = f"{name}{'' if pd else ' (no --project-dir)'}"
        rc, out = merge("api", 2, [(0, api[0]), (1, f)], project_dir=pd)
        eq(f"{what}: exit", rc, 1)
        eq(f"{what}: R3", r3(out), "fail")
        ps = problems(out)
        eq(f"{what}: exactly one entry", len(ps), 1)
        has(f"{what}: names the shard and the field", ps[0], f"mutants shard 1/2 produced no result: {want}")
        eq(f"{what}: the entry is CI", problems(out, "CI"), ps)
        eq(f"{what}: its MISSED mutant not counted", problems(out, "R3"), [])
        eq(f"{what}: only shard 0 counted", count_tested(out), "1/1")
# every shard without the field: nothing counted, one entry per shard, never pass
bare = [edit(api[k], f"api-{k}-bare.json", lambda d: d.pop("stack")) for k in (0, 1)]
rc, out = merge("api", 2, list(enumerate(bare)))
eq("all bare: exit", rc, 1)
eq("all bare: one entry per shard", sorted(problems(out)),
   [f"mutants shard {k}/2 produced no result: result has no stack field" for k in (0, 1)])
eq("all bare: no MISSED counted", problems(out, "R3"), [])

# 2. the right stack in another folder: named with its folder; unset --project-dir compares the stack alone
moved = edit(api[1], "api-1-moved.json", lambda d: d.update(stack={"stack": "python", "project_dir": "lib"}))
rc, out = merge("api", 2, [(0, api[0]), (1, moved)])
eq("other folder exit", rc, 1)
eq("other folder entry", problems(out), ["mutants shard 1/2 produced no result: result is for stack python in lib, not python in api"])
rc, out = merge("api", 2, [(0, api[0]), (1, moved)], project_dir=False)
eq("other folder, no --project-dir: counted", problems(out), [MISSED])
# a whole leg of another stack: one entry per result, nothing counted, never pass
rc, out = merge("api", 2, list(enumerate(web)))
eq("all foreign exit", rc, 1)
eq("all foreign: one entry per result", sorted(problems(out)),
   [f"mutants shard {k}/2 produced no result: result is for stack rust in web, not python in api" for k in (0, 1)])

# 3. the report: a duplicated stack is one CI fail entry naming it, however many repeats; the check fails
_, mapi = merge("api", 2, [(0, api[0]), (1, web[1])])  # wrong stack in api's merge: one CI entry
_, mapi_ok = merge("api", 2, list(enumerate(api)))  # api's own two shards: its survivor, no CI entry
_, mweb = merge("web", 2, list(enumerate(web)))
MAPI_OK, MWEB, MAPI_BAD = (save(n, d) for n, d in (("m-api-ok.json", mapi_ok), ("m-web.json", mweb),
                                                ("m-api-crossed.json", mapi)))
_, mbare = merge("api", 2, list(enumerate(bare)))
MBARE = save("m-api-bare.json", mbare)
gh = FakeGitHub()
try:
    API = ("api", "python", "api", {"r2": R2["api"], "mutants": MAPI_OK})
    WEB = ("web", "rust", "web", {"r2": R2["web"], "mutants": MWEB})
    rc, body = gh.report([WEB])
    eq("web alone (clean) exit", rc, 0)

    def ci(body):
        return [(e["stack"], e["severity"], e["problem"]) for e in entry_rows(body) if e["id"].startswith("CI-")]

    # api's merge holds a survivor; web is clean
    rc, body = gh.report([API, WEB, API])
    eq("same row twice: exit", rc, 1)
    dup = [c for c in ci(body) if "given" in c[2]]
    eq("same row twice: exactly one CI entry", len(dup), 1)
    eq("same row twice: a fail", dup[0][1], "fail")
    has("same row twice: names the stack", dup[0][2], "stack api (python in api) given twice")
    has("same row twice: the second is not counted", dup[0][2], "the second is not counted")
    eq("same row twice: api's MISSED once", [e["problem"] for e in entry_rows(body)].count(MISSED), 1)
    has("web still reports", body, "| web | rust | web | pass ")
    rc, body = gh.report([API, WEB, ("api2", "python", "api", {"r2": R2["api"], "mutants": MAPI_OK})])
    eq("same stack and folder under another name: exit", rc, 1)
    dup = [c for c in ci(body) if "given" in c[2]]
    eq("another name: exactly one CI entry", len(dup), 1)
    has("another name: names both", dup[0][2], "stack api (python in api) given twice: again as stack api2 (python in api)")
    rc, body = gh.report([API, API, WEB, API])
    eq("three times: exit", rc, 1)
    dup = [c for c in ci(body) if "given" in c[2]]
    eq("three times: exactly one CI entry", len(dup), 1)
    has("three times: says so", dup[0][2], "given 3 times")
    has("three times: only the first counted", dup[0][2], "only the first is counted")
    # the first row with no result: its own `produced no result` entry and the duplicate entry
    rc, body = gh.report([("api", "python", "api", {"r2": os.path.join(os.getcwd(), "never-written.json")}), WEB, API])
    eq("first row empty: exit", rc, 1)
    eq("first row empty: one duplicate entry", len([c for c in ci(body) if "given" in c[2]]), 1)
    has("first row empty: its own entry", body, "produced no result")
    # 4. a merge's CI entries (wrong stack, no stack field) reach the comment in the leg's row and fail the check
    for what, m, want in (("wrong stack", MAPI_BAD, "result is for stack rust in web, not python in api"),
                          ("no stack field", MBARE, "result has no stack field")):
        rc, body = gh.report([("api", "python", "api", {"r2": R2["api"], "mutants": m}), WEB])
        eq(f"{what} in the comment: exit", rc, 1)
        has(f"{what}: api row fails", body, "| api | python | api | fail ")
        got = [c for c in ci(body) if want in c[2]]
        eq(f"{what}: in api's rows of the entries table", sorted({(s, sev) for s, sev, _ in got}), [("api", "fail")])
        hasnt(f"{what}: never all pass", body, "all pass")
finally:
    gh.close()

checkout_untouched()
print("mech-review-mutants/stacks/misuse ok")
