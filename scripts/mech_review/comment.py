"""Comment poster: render the mech-review contract JSON into one sticky PR comment, find or edit it.

Pure render + exit code here; find-or-edit transport is injected (call(method, url, payload) -> JSON).
Stdlib only.
"""
import json
import re

from .mutants import risk_text
from .waiver import MARKER, PLACEHOLDER
COMMENT_LIMIT = 60000  # GitHub caps a comment at 65536 chars; keep headroom
OVERSIZE_ROWS = 50
CELL_MAX = 200
WAIVER_LINES_MAX = 20  # per kind: Waived, Waiver ignored
CUT_NOTE = "Comment cut at the size limit. Full result: `mech-review-json` artifact of this run."


def _line(text):
    """One line, cut to CELL_MAX like a table cell."""
    s = str(text).replace("\r", " ").replace("\n", " ")
    if len(s) > CELL_MAX:
        s = s[:CELL_MAX - 1] + "…"
    return s


def _cell(text):
    return _line(text).replace("|", "\\|")


def _span(text):
    """A code span for text from the PR outside the table: no markdown, HTML or @-ping. Its delimiter is longer than
    any backtick run inside; text that starts or ends with a backtick is padded with a space."""
    d = "`" * (max((len(m) for m in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{d}{pad}{text}{pad}{d}"


def _fence(text):
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _label(e):
    """Human severity: a fail entry of class needs-human reads needs-human. The JSON keeps severity fail."""
    label = "needs-human" if e["severity"] == "fail" and e.get("class") == "needs-human" else e["severity"]
    if e.get("blocked"):  # its check is n/a (a failed R0, #20): the entry still counts
        label += f" ({e.get('check', '')} blocked by {e['blocked']})"
    return label


def headline(env):
    """Summary line, `fail` read as `needs-human` when every fail entry is needs-human. Otherwise unchanged."""
    fails = [e for e in env["entries"] if e["severity"] == "fail"]
    if fails and all(e.get("class") == "needs-human" for e in fails) and env["summary"].startswith("fail "):
        return "needs-human " + env["summary"][len("fail "):]
    return env["summary"]


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _fmt(x):
    """seconds for a human line: up to two decimals, no trailing zeros (53 -> 53, 1.8 -> 1.8, 0.25 -> 0.25)."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _timing_lines(env):
    """One human line under the headline when R3 ran (its count and timing); its tested/total per risk class when the
    cap cut the run (checks.R3.by_risk, #122; malformed or absent: no line); the slowest mutants when it is partial.
    The JSON block carries every field; a field that is not there is left out here too."""
    c = (env.get("checks") or {}).get("R3") or {}
    if c.get("status") not in ("pass", "fail", "partial"):
        return []
    t = c.get("timing") or {}
    tested, total = c.get("tested"), c.get("total")
    if tested is None and not t:
        return []
    parts = []
    if _num(tested) and tested:  # nothing tested (0/0 or 0/N): no count, the wall time says the rest
        parts.append(f"{tested}/{total if _num(total) else '?'} mutants")
    if _num(t.get("wall_s")):
        parts.append(f"{_fmt(t['wall_s'])}s wall")
    detail = []
    if _num(t.get("mutant_build_s")):
        detail.append(f"build {_fmt(t['mutant_build_s'])}s")
    if _num(t.get("mutant_test_s")):
        detail.append(f"test {_fmt(t['mutant_test_s'])}s")
    if _num(t.get("avg_s_per_mutant")):
        seg = f"avg {_fmt(t['avg_s_per_mutant'])}s per mutant"
        if detail:
            seg += f" ({', '.join(detail)})"
        parts.append(seg)
    elif detail:
        parts.append(f"({', '.join(detail)})")
    base = []  # the baseline step's seconds, once for the whole run (#46)
    if _num(t.get("baseline_build_s")):
        base.append(f"build {_fmt(t['baseline_build_s'])}s")
    if _num(t.get("baseline_test_s")):
        base.append(f"test {_fmt(t['baseline_test_s'])}s")
    if base:
        parts.append(f"baseline ({', '.join(base)})")
    lines = ["R3 timing: " + ", ".join(parts)] if parts else []
    risk = risk_text(c.get("by_risk"))  # what the count stands for, when the cap cut the run (#122)
    if risk:
        lines.append(f"R3 by risk class, tested/total: {risk}")
    slow = [x for x in (t.get("slowest") or []) if isinstance(x, dict) and _num(x.get("s"))]
    if c.get("status") == "partial" and slow:
        names = [f"{_cell(x.get('name', '')).replace('`', chr(39))} {_fmt(x['s'])}s" for x in slow[:5]]
        lines.append("R3 slowest: " + ", ".join(names))
    return lines


def _table(entries, by_stack=False):
    """The entries table; with several stacks (#17) a stack column names each entry's stack."""
    rows = [
        "| id | stack | severity | file:line | problem | forbidden |" if by_stack else
        "| id | severity | file:line | problem | forbidden |",
        "|---|---|---|---|---|---|" if by_stack else "|---|---|---|---|---|",
    ]
    for e in entries:
        stack = f" {_cell(e.get('stack', ''))} |" if by_stack else ""
        rows.append(f"| {_cell(e['id'])} |{stack} {_cell(_label(e))} | {_cell(e['file'])}:{e['line']} | "
                    f"{_cell(e['problem'])} | {_cell(e['forbidden'])} |")
    return "\n".join(rows)


def _stack_rows(env):
    """Several stacks (#17): a row per stack, its name, adapter, project dir and its own result. None for one stack."""
    stacks = env.get("stacks") or []
    if not stacks:
        return []
    return (["| stack | adapter | project dir | result |", "|---|---|---|---|"]
            + [f"| {_cell(s['name'])} | {_cell(s['stack'])} | {_cell(s['project_dir'])} | {_cell(s['summary'])} |"
               for s in stacks])


def _each_stack(env, lines_of):
    """lines_of(env), or with several stacks (#17) lines_of each stack's own checks, each line named by its stack."""
    stacks = env.get("stacks") or []
    if not stacks:
        return lines_of(env)
    return [f"{_cell(s['name'])}: {line}" for s in stacks for line in lines_of({"checks": s["checks"]})]


CHECK_ORDER = ("R0", "R1", "R2", "R3", "R4", "D")


def _not_run_lines(env):
    """One line under the headline when a check is n/a: it did not run, and its note names the input to set.
    The status and the JSON are unchanged."""
    checks = env.get("checks") or {}
    na = [f"{c} ({(checks.get(c) or {}).get('note', '')})" for c in CHECK_ORDER
          if (checks.get(c) or {}).get("status") == "n/a"]
    return ["Did not run: " + "; ".join(na)] if na else []


def _r0_lines(env):
    """One line under the headline when R0 ran (#20): its note (cases proved, unproven, failed), as a code span: an
    adapter file's text from the PR reaches it through the case results."""
    c = (env.get("checks") or {}).get("R0") or {}
    return [f"R0: {_span(_line(c['note']))}"] if c.get("note") else []


def _plan_lines(env):
    """One line per drift message (#56: planned, retiring and vanished stacks), as a code span: the text holds paths and
    names from the PR. None without a plan."""
    d = (env.get("checks") or {}).get("D") or {}
    return _capped([f"Stack plan: {_span(_line(m))}" for m in d.get("messages") or []], "stack plan messages")


def _login(name):
    """A login in code style, so nobody is pinged; a backtick cannot close the span."""
    return f"`{_cell(name).replace('`', chr(39))}`"


def _capped(lines, what):
    """The first WAIVER_LINES_MAX lines, then one line counting the rest."""
    more = len(lines) - WAIVER_LINES_MAX
    return lines[:WAIVER_LINES_MAX] + ([f"…and {more} more {what}"] if more > 0 else [])


def _waiver_lines(env):
    """One line per waived entry: who let it through, and why. Then one per ignored waiver (`waivers_ignored`, set
    by mech-comment.py): who posted it and why it did not count. Each kind is capped, so the comment fits."""
    return (_capped([f"Waived: {_cell(e['id'])} by {_login((e.get('waiver') or {}).get('by', '?'))}: "
                     f"{_cell((e.get('waiver') or {}).get('reason', ''))}"
                     for e in env["entries"] if e["severity"] == "waived"], "waived")
            + _capped([f"Waiver ignored: {_cell(r['id'])} by {_login(r['by'])}: {_cell(r['why'])}"
                       for r in env.get("waivers_ignored") or []], "ignored"))


WAIVE_HELP = (f"People with write access can waive a `fail` entry: copy its line below, replace `{PLACEHOLDER}` with the "
              "reason, and post it as a PR comment. The check re-runs on its own where the mech-waive workflow is set up; "
              "otherwise re-run this run's failed job (`report`).")
WAIVE_OMITTED = (f"Waiver lines left out (comment size limit): post `/mech-waive <id> {PLACEHOLDER}` with an id "
                 "from the table.")


def _code(text):
    fence = _fence(text)
    return [fence, text, fence]


def _ready_made(waivable):
    """Per waivable entry a label and a code block holding the line to post; with 2 or more, one block for all."""
    lines = []
    for e in waivable:
        lines += ["", f"{_cell(e['id'])} · {_span(_line(e['problem']))} ({_span(_line(e['file']) + ':' + str(e['line']))})",
                  *_code(f"/mech-waive {e['id']} {PLACEHOLDER}")]
    if len(waivable) >= 2:
        lines += ["", "All fail entries at once", *_code("\n".join(f"/mech-waive {e['id']} {PLACEHOLDER}" for e in waivable))]
    return lines


def _body(env, shown, json_text, omit_lines=False):
    entries = env["entries"]
    lines = [MARKER, "## mech-review", "", f"**{headline(env)}**", ""]
    stacks = _stack_rows(env)
    if stacks:
        lines += stacks + [""]
    not_run = _each_stack(env, _not_run_lines)
    if not_run:
        lines += not_run + [""]
    r0 = _each_stack(env, _r0_lines)
    if r0:
        lines += r0 + [""]
    waived = _waiver_lines(env)
    if waived:
        lines += waived + [""]
    plan = _plan_lines(env)
    if plan:
        lines += plan + [""]
    timing = _each_stack(env, _timing_lines)
    if timing:
        lines += timing + [""]
    lines += [f"head `{env['head']}`", ""]
    if not entries:
        lines.append("No entries.")
    else:
        lines.append(_table(shown, by_stack=bool(env.get("stacks"))))
        if len(shown) < len(entries):
            lines += ["", f"_showing first {len(shown)} of {len(entries)} entries_"]
        waivable = [e for e in entries if e["severity"] == "fail" and e.get("check") in CHECK_ORDER]  # never CI
        if waivable:
            lines += ["", WAIVE_HELP]
            lines += ["", WAIVE_OMITTED] if omit_lines else _ready_made(waivable)
    lines.append("")
    if json_text is None:
        lines.append("JSON omitted (comment size limit). Full result: `mech-review-json` artifact of this run.")
    else:
        fence = _fence(json_text)
        lines += ["### JSON", "", f"{fence}json", json_text, fence]
    return "\n".join(lines) + "\n"


def render(env):
    """The comment, shrunk to fit COMMENT_LIMIT step by step: first the ready-made waiver lines give way, then the
    JSON and all but the first OVERSIZE_ROWS rows. Still too big (rows of wide cells): cut at a line, with a note.
    That body has no code block, so a cut cannot leave one open."""
    json_text = json.dumps(env, indent=2)
    for body in (_body(env, env["entries"], json_text), _body(env, env["entries"], json_text, omit_lines=True),
                 _body(env, env["entries"][:OVERSIZE_ROWS], None, omit_lines=True)):
        if len(body) <= COMMENT_LIMIT:
            return body
    tail = "\n\n" + CUT_NOTE + "\n"
    return body[:body[:COMMENT_LIMIT - len(tail) + 1].rindex("\n")] + tail  # a newline at index n keeps n chars


def render_crash(head, reason):
    return "\n".join([
        MARKER,
        "## mech-review",
        "",
        f"**no result** for head `{head}`",
        "",
        f"reason: {reason}",
        "",
        "The check fails. See the job log.",
        "",
    ])


def exit_code(env):
    """1 on any fail entry, or any check with status fail (an entry lost on the way must not pass the check)."""
    failed = any(c.get("status") == "fail" for c in (env.get("checks") or {}).values() if isinstance(c, dict))
    return 1 if failed or any(e["severity"] == "fail" for e in env["entries"]) else 0


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f"GitHub API {status}: {body}")
        self.status = status
        self.body = body


PER_PAGE = 100
DEFAULT_AUTHOR = "github-actions[bot]"  # login of the GITHUB_TOKEN actor; override with MECH_COMMENT_AUTHOR


def comments(call, api, repo, pr):
    """Every issue comment on the PR, oldest first, paging until a short page."""
    page = 1
    while True:
        items = call("GET", f"{api}/repos/{repo}/issues/{pr}/comments?per_page={PER_PAGE}&page={page}", None)
        yield from items
        if len(items) < PER_PAGE:
            return
        page += 1


def find_marker(call, api, repo, pr, author=DEFAULT_AUTHOR):
    """Id of the first issue comment by `author` whose body starts with MARKER. None if absent."""
    for c in comments(call, api, repo, pr):
        if c.get("body") and c["body"].startswith(MARKER) and (c.get("user") or {}).get("login") == author:
            return c["id"]
    return None


def upsert(call, api, repo, pr, body, author=DEFAULT_AUTHOR):
    """Edit the author's marker comment in place, or create it. Returns (action, comment id)."""
    cid = find_marker(call, api, repo, pr, author)
    if cid is None:
        res = call("POST", f"{api}/repos/{repo}/issues/{pr}/comments", {"body": body})
        return "created", res["id"]
    call("PATCH", f"{api}/repos/{repo}/issues/comments/{cid}", {"body": body})
    return "updated", cid


def publish(call, api, repo, pr, head, body, author=DEFAULT_AUTHOR):
    """upsert, unless the PR head has moved past `head`: then leave the comment alone.
    Returns ("superseded", current head sha) or the upsert result. Check-then-write: a
    newer run landing between the GET and the write can still be overwritten."""
    current = call("GET", f"{api}/repos/{repo}/pulls/{pr}", None)["head"]["sha"]
    if current != head:
        return "superseded", current
    return upsert(call, api, repo, pr, body, author)


def http_call(token):
    """Real transport: urllib with the workflow token. Non-2xx and unreachable hosts raise ApiError."""
    import urllib.error
    import urllib.request

    def call(method, url, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "ekit-mech-review",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            with e:  # the error is a response too: close it, or its socket leaks (ResourceWarning)
                body = e.read().decode(errors="replace")
            raise ApiError(e.code, body) from None
        except urllib.error.URLError as e:
            raise ApiError(0, f"unreachable: {e.reason}") from None
        return json.loads(raw) if raw else None

    return call
