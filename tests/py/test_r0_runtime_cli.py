"""R0 runtime half (#21) through the repo's own adapter file (no --adapter: `.ekit/adapters/<name>.toml` at the base,
cli._not_built) and `r0 --fingerprint` on a stack the repo defines, through cli.main in this process. CI's R3 on #76
found these lines untested: the red envelope carries R0 only with --r0, and `r0 --fingerprint` refuses an unknown stack
but proceeds for a repo's adapter file."""
import json
import os

import _kit
from test_r0_runtime import MINIRUN, MINIRUN_FX, Case

ADAPTER = ".ekit/adapters/minirun.toml"


class _RepoAdapter(Case):
    """a repo whose own adapter file (minirun) and its fixtures sit at the base: no --adapter is passed."""

    def setUp(self):
        super().setUp()
        with open(MINIRUN) as f:
            text = f.read()
        files = {ADAPTER: text}
        for top, _, names in os.walk(MINIRUN_FX):
            for n in names:
                full = os.path.join(top, n)
                with open(full) as f:
                    files[".ekit/adapters/minirun.r0/" + os.path.relpath(full, MINIRUN_FX).replace(os.sep, "/")] = f.read()
        self.base = self.commit(files)

    def cli(self, check, *extra):
        r = _kit.run_cli([check, "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", "minirun",
                          "--test-paths", "tests/**", *extra])
        self.assertIn(r.returncode, (0, 1), r.stderr + r.stdout)
        return json.loads(r.stdout)


class RepoAdapterFile(_RepoAdapter):
    def test_red_with_r0_carries_reds_r0(self):
        env = self.cli("red", "--r0", self.cache)
        c = env["checks"]["R0"]
        self.assertEqual((c["status"], c["half"], c["part"], c["ran"]), ("pass", "runtime", "run", True), c)
        self.assertRegex(c["note"], r"^runtime half \(run\): fingerprint [0-9a-f]{12} \(ran\); census: 2/2 listed tests "
                                    r"found; fixtures census: 3/3; assert density: 0 of 2 tests with no recognised "
                                    r"assert, 0% \(limit 10%\); controls: 5 of 5 read right$")
        self.assertEqual({k: env["checks"][k]["status"] for k in ("R1", "R4")}, {"R1": "skipped", "R4": "pass"})

    def test_red_without_r0_has_no_r0(self):
        env = self.cli("red")
        self.assertNotIn("R0", env["checks"])
        self.assertEqual(env["checks"]["R4"]["status"], "pass")

    def test_all_with_r0_carries_reds_r0_in_place_of_the_skipped_static_half(self):
        env = self.cli("all", "--r0", self.cache)
        c = env["checks"]["R0"]
        self.assertEqual((c["status"], c["half"], c["part"]), ("pass", "runtime", "run"), c)

    def test_all_without_r0_keeps_the_skipped_static_half(self):
        env = self.cli("all")
        self.assertEqual(env["checks"]["R0"], {"status": "skipped",
                                               "note": "not run by all on the repo's adapter file: r0 proves it"})


class FingerprintStack(_RepoAdapter):
    def fp(self, stack):
        return _kit.run_cli(["r0", "--repo", self.repo, "--base", self.base, "--head", self.base, "--stack", stack,
                             "--fingerprint", "run"])

    def test_an_unknown_stack_with_no_adapter_is_a_usage_error(self):
        r = self.fp("nosuch")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("argument --stack: invalid choice: 'nosuch'", r.stderr)

    def test_a_repo_adapter_file_whose_stack_is_no_built_in_proceeds(self):
        r = self.fp("minirun")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["part"], got["key"]), ("run", f"ekit-r0-run-{got['fingerprint']}"))
        self.assertEqual(got["probes"], ["mini --version: mini 1.0.0"])
        red = self.cli("red", "--r0", self.cache)  # the key red computes for the same repo adapter file
        self.assertEqual(red["checks"]["R0"]["fingerprint"], got["fingerprint"])


del Case  # imported for subclassing: not run again from this module
