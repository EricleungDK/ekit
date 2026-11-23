"""R2 test-diff guard: path rules per change, then r2_file per source file (text in, entries out)."""
import difflib
import re
from collections import Counter

from .gitio import added_lines, blob, changes
from .globs import any_glob
from .parser_cmd import ParserError
from .report import entry

def unmatched(xs, ys):
    """xs minus exact (fn, kind, left, right) matches in ys, multiset-aware."""
    # eq/ne match on operands; other asserts (assert!(cond)) match on their text
    key = lambda a: (a.fn, a.kind, a.left, a.right) if a.kind != "other" else (a.fn, a.kind, re.sub(r"\s+", "", a.text))
    pool = Counter(key(y) for y in ys)
    out = []
    for x in xs:
        if pool[key(x)]:
            pool[key(x)] -= 1
        else:
            out.append(x)
    return out


def r2(rv, protected_globs):
    """R2 over mb..head: path rules (protected paths, mutation config) per change, then r2_file per source file.
    An adapter file's parser command that fails (ParserError, #27) makes every file's entries one blocking CI entry,
    never a fallback; the path rules stay."""
    repo, mb, head, adapter, test_globs, _ = rv
    entries, files, failed = [], [], None
    added = added_lines(repo, mb, head)
    for ch in changes(repo, mb, head):
        if any_glob(ch.old or "", protected_globs) or any_glob(ch.new or "", protected_globs):
            entries.append(entry("R2", ch.new or ch.old, 0, "protected-path", "needs-human", "fail",
                                 f"protected path changed: {ch.new or ch.old}",
                                 "move this change to its own human-reviewed PR; a human decides",
                                 "editing CI, gate scripts or agent docs to get the gate green"))
        cfg_path = ch.new or ch.old
        what = adapter.mutation_config(cfg_path, lambda: (blob(repo, mb, ch.old) if ch.old else None,
                                                          blob(repo, head, ch.new) if ch.new else None))
        if what:
            entries.append(entry("R2", cfg_path, 0, "mutation-config", "needs-human", "fail",
                                 f"mutation config changed: {what} in {cfg_path}",
                                 "move this change to its own human-reviewed PR; a person decides what R3 may leave out",
                                 "hiding code from mutation testing (R3)"))
        # a source file renamed to a non-source path is a deletion; a non-source file renamed to source is an addition
        old = ch.old if ch.old and adapter.classify(ch.old, test_globs) is not None else None
        new = ch.new if ch.new and adapter.classify(ch.new, test_globs) is not None else None
        if (old is None and new is None) or failed:
            continue
        try:
            files += r2_file(adapter, test_globs, old, new,
                             blob(repo, mb, old) if old else None, blob(repo, head, new) if new else None,
                             {ln for ln, _ in added.get(new, [])})
        except ParserError as e:
            failed = parser_entry(new or old, e)
    return entries + ([failed] if failed else files)


def parser_entry(path, err):
    """the one CI entry of a parser command that failed on the file at path (#27): R2 cannot read the stack."""
    return entry("CI", path, 0, "parser", "adapter-fix", "fail", f"the adapter's parser failed: {err}",
                 "fix the parser command or its pinned install step in the adapter file, in a PR of its own; R2 reads "
                 "nothing of this stack until the parser runs", "falling back to patterns, or skipping R2, when the "
                 "parser fails")


def r2_file(adapter, test_globs, old, new, before, after, added=frozenset()):
    """R2 rules for one source file, from its text alone (no git). Entries are not finalized.
    old/new: the file's path at base/head when it is a source file of this stack, else None. before/after: the text at
    those paths (None with the path). added: head line numbers the change adds; suppressions and mutation skips count
    only there. A side that does not parse is the only result: its test changes cannot be checked."""
    path = new or old
    if hasattr(adapter, "at"):  # a parser-backed adapter (#27): its command gets the file's path
        adapter = adapter.at(path)
    unparsed = _unparsed(adapter, path, before, after)
    if unparsed:
        return unparsed
    # each side is classified by its own path: a file moved between test and prod paths is judged per side
    whole_b = old is not None and adapter.classify(old, test_globs) == "test"
    whole_a = new is not None and adapter.classify(new, test_globs) == "test"
    # a side whose path cannot hold tests (python: a production file not named like a test file) has none to read
    held_b = before if old is not None and adapter.holds_tests(old, test_globs) else None
    held_a = after if new is not None and adapter.holds_tests(new, test_globs) else None
    bas = [a for a in adapter.assertions(held_b) if whole_b or a.scope] if held_b is not None else []
    aas = [a for a in adapter.assertions(held_a) if whole_a or a.scope] if held_a is not None else []
    bfns = adapter.test_fns(held_b) if held_b is not None else []
    afns = adapter.test_fns(held_a) if held_a is not None else []
    gone, renamed, changed = _renames(bfns, afns, bas, aas, held_b, held_a)
    entries = _removed(path, gone) + _renamed_changed(path, changed)
    entries += _markers(adapter, path, afns, bfns, renamed)
    if before is not None:
        entries += _assert_counts(adapter, path, after, bas, aas, afns)
    entries += _changed_asserts(path, bas, aas)
    if new is not None:
        entries += _suppressions(adapter, new, after, added)
        if adapter.classify(new, test_globs) == "prod":
            entries += _mutation_skips(adapter, new, after, added)
    return entries


def _unparsed(adapter, path, before, after):
    """a file the stack cannot parse is a truthful fail: one entry per side that does not parse. With an adapter file
    the cause may be the file's lexer table, not the PR: a person decides (needs-human)."""
    out = []
    cls, hint = "agent-fixable", "fix the syntax error: this file cannot be checked against base"
    if adapter.from_file:
        cls, hint = "needs-human", ("fix the syntax error; if the file is valid, the adapter file's lexer table cannot "
                                    "read it: a person fixes the adapter file")
    for lab, text in (("base", before), ("head", after)):
        err = adapter.parse_error(text) if text is not None else None
        if err:
            where = "base file" if lab == "base" else "file"
            out.append(entry("R2", path, err[0], f"unparseable:{lab}", cls, "fail",
                             f"{where} does not parse: {err[1]} (line {err[0]})", hint,
                             "unparseable file hides test changes"))
    return out


RENAME_MATCH = 0.6  # difflib's ratio over the non-assert body lines, for a renamed test whose assertions changed (#41)
RENAME_SHARED = 3  # non-assert body lines the two must share, at least, and at least half of the old test's


def _body(text, span, skip=frozenset()):
    """the stripped non-blank lines of a test's body, span (first, last) from the adapter (after the signature, up to
    its end), leaving out the line numbers in skip (its assert lines). No span: no body."""
    if not span:
        return []
    lines = text.splitlines()
    first, last = span
    return [ln.strip() for no, ln in enumerate(lines[first - 1:last], start=first) if ln.strip() and no not in skip]


def _renames(bfns, afns, bas, aas, before=None, after=None):
    """(removed fns, {new name: old fn}, [(old fn, new fn)]). A removed fn whose asserts reappear unchanged in a new fn
    (one-to-one, non-empty) is a rename, not a removal. Then a removed fn with asserts and a new fn with no fewer, whose
    non-assert body lines (the adapter's body span) match at least RENAME_MATCH and share at least RENAME_SHARED lines
    and half the old test's (one-to-one, best match first), are a rename whose assertions changed: listed for a confirm
    entry."""
    names = {f.name for f in afns}
    by_name = {f.name for f in bfns}
    sigs = lambda xs, n: sorted(re.sub(r"\s+", "", a.text) for a in xs if a.fn == n)
    gone = [f for f in bfns if f.name not in names]
    renamed = {}
    for nf in (f for f in afns if f.name not in by_name):
        sig = sigs(aas, nf.name)
        if not sig:
            continue
        for rf in gone:
            if sigs(bas, rf.name) == sig:
                renamed[nf.name] = rf
                gone.remove(rf)
                break
    changed = []
    if before is not None and after is not None:
        new = [f for f in afns if f.name not in by_name and f.name not in renamed]
        pairs = []
        for rf in gone:
            had = sigs(bas, rf.name)
            if not had:  # no assert: no "assertions changed" to confirm
                continue
            rb = _body(before, rf.body, {a.line for a in bas if a.fn == rf.name})
            for nf in new:
                if len(sigs(aas, nf.name)) < len(had):  # a dropped assert is no rename
                    continue
                nb = _body(after, nf.body, {a.line for a in aas if a.fn == nf.name})
                m = difflib.SequenceMatcher(None, rb, nb, autojunk=False)
                shared = sum(b.size for b in m.get_matching_blocks())
                if rb and nb and shared >= RENAME_SHARED and 2 * shared >= len(rb) and m.ratio() >= RENAME_MATCH:
                    pairs.append((-m.ratio(), rf.line, nf.line, rf, nf))
        taken_old, taken_new = set(), set()
        for _, _, _, rf, nf in sorted(pairs, key=lambda x: x[:3]):
            if rf.name in taken_old or nf.name in taken_new:
                continue
            taken_old.add(rf.name)
            taken_new.add(nf.name)
            renamed[nf.name] = rf
            changed.append((rf, nf))
        gone = [f for f in gone if f.name not in taken_old]
    return gone, renamed, changed


def _renamed_changed(path, changed):
    return [entry("R2", path, nf.line, f"renamed:{rf.name}", "agent-fixable", "confirm",
                  f"test `{rf.name}` renamed to `{nf.name}`, assertions changed",
                  "confirm the spec changed what this test asserts and the new name says what it now checks",
                  "renaming a test to hide a changed or weakened assertion") for rf, nf in changed]


def _removed(path, gone):
    return [entry("R2", path, f.line, f.name, "agent-fixable", "fail", f"test fn `{f.name}` removed",
                  "restore the test and make the code satisfy it; a removed test is not a fix",
                  "deleting or renaming a test to hide a failure") for f in gone]


def _markers(adapter, path, afns, bfns, renamed):
    """ignore / only / should_panic newly on a test (a renamed test keeps its old fn's markers)."""
    by_name = {f.name: f for f in bfns}
    out = []
    for f in afns:
        prev = by_name.get(f.name) or renamed.get(f.name)
        if "ignore" in f.markers and not (prev and "ignore" in prev.markers):
            out.append(entry("R2", path, f.line, f"ignore:{f.name}", "agent-fixable", "fail",
                             adapter.ignored_text(f.name),
                             "make it pass or fix the code it covers; do not mark it ignored",
                             "#[ignore] / skip / xfail / only on a test"))
        if "only" in f.markers and not (prev and "only" in prev.markers):
            out.append(entry("R2", path, f.line, f"only:{f.name}", "agent-fixable", "fail",
                             f"test `{f.name}` marked only: the other tests do not run",
                             "remove .only: run the whole suite, not one test",
                             "#[ignore] / skip / xfail / only on a test"))
        if "should_panic" in f.markers and prev and "should_panic" not in prev.markers:
            out.append(entry("R2", path, f.line, f"should-panic:{f.name}", "agent-fixable", "confirm",
                             f"test `{f.name}` now expects a panic (#[should_panic] added)",
                             "a panic-expecting test passes on any panic; assert the error or value instead",
                             "adding #[should_panic] to an existing test"))
    return out


def _assert_counts(adapter, path, after, bas, aas, afns):
    """assert count per surviving test fn (by name). A fn that loses asserts is a fail unless a helper (non-test fn) it
    calls by name gained at least as many (extraction); each gained assert explains one lost assert, once. Asserts
    outside test fns keep a per-file count."""
    out = []
    head_fns = {f.name for f in afns}
    b_cnt = Counter(a.fn for a in bas if a.fn in head_fns)
    a_cnt = Counter(a.fn for a in aas if a.fn in head_fns)
    gain = Counter()
    for h in {a.owner for a in aas if a.fn is None and a.owner}:
        hb = sum(1 for a in bas if a.fn is None and a.owner == h)
        ha = sum(1 for a in aas if a.fn is None and a.owner == h)
        if ha > hb:
            gain[h] = ha - hb
    calls = adapter.calls(after) if after is not None else {}
    for f in afns:
        n = f.name
        lost = b_cnt[n] - a_cnt[n]
        if lost <= 0:
            continue
        called = calls.get(n, set())
        for h in sorted(gain):
            take = min(gain[h], lost) if h.rsplit("::", 1)[-1] in called else 0
            gain[h] -= take
            lost -= take
        if lost > 0:
            out.append(entry("R2", path, f.line, f"assert-count:{n}", "agent-fixable", "fail",
                             f"assertions in test `{n}` dropped from {b_cnt[n]} to {a_cnt[n]}",
                             "restore the dropped assertions; strengthen a test instead of removing one",
                             f"fewer asserts in test {n}"))
    helper_before = sum(1 for a in bas if a.fn is None)
    helper_after = sum(1 for a in aas if a.fn is None)
    if helper_after < helper_before:
        out.append(entry("R2", path, 0, "assert-count", "agent-fixable", "fail",
                         f"assertions outside test fns in `{path}` dropped from {helper_before} to {helper_after}",
                         "restore the dropped assertions; strengthen a test instead of removing one",
                         f"fewer asserts in changed test file {path}"))
    return out


def _changed_asserts(path, bas, aas):
    """expected value changed (same fn and kind, one operand unchanged, the other changed), then any other assert
    removed and another added in the same fn (replaced in place). Both are confirm."""
    out = []
    removed = unmatched(bas, aas)
    added_a = unmatched(aas, bas)
    used, paired = set(), set()
    for ri, r in enumerate(removed):
        if r.kind not in ("eq", "ne"):
            continue
        for i, h in enumerate(added_a):
            if i in used or h.fn != r.fn or h.kind != r.kind:
                continue
            l_same, r_same = h.left == r.left, h.right == r.right
            if l_same == r_same:
                continue
            used.add(i)
            paired.add(ri)
            unchanged = r.left if l_same else r.right
            was, now = (r.right, h.right) if l_same else (r.left, h.left)
            where = r.fn or "<module>"
            out.append(entry("R2", path, h.line, f"expected:{r.fn or ''}|{unchanged}", "agent-fixable", "confirm",
                             f"expected value changed in `{where}`: was {was}, now {now}",
                             "confirm the new value is the spec'd behaviour, not the buggy output",
                             "editing an expected value to match the code's current output"))
            break
    spare = [h for i, h in enumerate(added_a) if i not in used]
    for ri, r in enumerate(removed):
        if ri in paired:
            continue
        for j, h in enumerate(spare):
            if h.fn != r.fn:
                continue
            del spare[j]
            where = r.fn or "<module>"
            out.append(entry("R2", path, h.line, f"assert-replaced:{r.fn or ''}", "agent-fixable", "confirm",
                             f"assertion replaced in `{where}`: `{r.text}` -> `{h.text}`",
                             "keep the assertion at least as strict; the reviewer confirms an intended change",
                             "weakening an assertion in place"))
            break
    return out


def _touches(line, end_line, added):
    return any(ln in added for ln in range(line, end_line + 1))


def _suppressions(adapter, path, after, added):
    """a lint suppression without a reason, on a line the change adds."""
    out = []
    for sup in adapter.suppressions(after):
        if sup.reason or not _touches(sup.line, sup.end_line, added):
            continue
        problem, hint = adapter.suppression_text(sup)
        out.append(entry("R2", path, sup.line, sup.lints, "agent-fixable", "fail", problem, hint,
                         "silencing a lint without a reason"))
    return out


def _mutation_skips(adapter, path, after, added):
    """a marker that hides production code from R3, on a line the change adds."""
    return [entry("R2", path, line, "mutation-skip", "needs-human", "fail",
                  f"mutation skip added: `{marker}` hides this code from R3",
                  "remove it and add the test R3 asks for; if the code truly cannot be tested, a person decides",
                  "hiding code from mutation testing (R3)")
            for line, end_line, marker in adapter.mutation_skips(after) if _touches(line, end_line, added)]
