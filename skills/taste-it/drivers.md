# Drivers

Install the deliverable the way a user gets it, **into the scenario's temp cwd**, then drive the installed copy. `$EKIT_REPO` is the repo under test.

| Deliverable | Install (inside the temp cwd) | Drive | Assert |
|---|---|---|---|
| Python CLI | `python3 -m venv v && v/bin/pip install "$EKIT_REPO"` | `v/bin/<cmd>`: args, stdin, exit code | stdout/stderr, exit code, files written |
| Node CLI | `npm install --prefix . "$(npm pack "$EKIT_REPO" \| tail -1)"` | `./node_modules/.bin/<cmd>` | same |
| Rust CLI | `cargo install --path "$EKIT_REPO" --root .` | `./bin/<cmd>` | same |
| TUI | as its CLI row | `tmux new -d`, `send-keys`, `capture-pane`; or `expect` | pane text |
| HTTP API | as its CLI row; launch the server in the background, wait for the port | `curl`, `jq` | status, body fields; kill the server on exit |
| Web UI | launch the server | `playwright` script | DOM text; a screenshot of each asserted state saved to `$EKIT_ARTIFACT_DIR`, the reviewer's proof (the assertion stays on text) |
| Library | build or pack it, install the artifact into a fresh venv or project | consumer script importing it | script output, exit code |
| Batch job | run the entrypoint on fixture input | shell | output files, row counts, rerun idempotence |
| Claude plugin | `claude plugin marketplace add <repo>`, `claude plugin install` (the one row that cannot stay in the temp cwd: a plugin installs into the user's Claude config, so uninstall it when the scenario ends) | `claude -p "<prompt>"` | output text, hook JSON, files |

The table's commands are shell lines. In a `run.py` (the default run file) each is an argv list run from the temp cwd, so it runs the same on every OS:

```python
import os, shutil, subprocess, sys
repo = os.environ["EKIT_REPO"]
subprocess.run([sys.executable, "-m", "venv", "v"], check=True)        # Python CLI: python3 -m venv v
bin_ = os.path.join("v", "Scripts" if os.name == "nt" else "bin")      # v/bin/ on POSIX, v\Scripts\ on Windows
subprocess.run([os.path.join(bin_, "pip"), "install", repo], check=True)
r = subprocess.run([os.path.join(bin_, "<cmd>"), "--help"], capture_output=True, text=True)
assert r.returncode == 0, r.stderr                                     # a failed assert exits 1: FAIL (the runner unsets PYTHONOPTIMIZE)
```

Start other tools through `shutil.which("npm")`, `shutil.which("cargo")` (on Windows `npm` is `npm.cmd`, which a bare name does not find); a server goes in `subprocess.Popen(...)`, stopped in a `finally` (the runner also stops what is left when the scenario ends). `tmux` and `expect` exist on POSIX only: a TUI scenario that needs them stays a `run.sh`.

Not an install a user gets, so not a taste:
- **Editable or linked** (`pip install -e`, `npm link`, a bare `npm install <folder>`): the source tree is what runs, and packaging mistakes (a file missing from the wheel or tarball) stay hidden.
- **Global** (`npm i -g`, `pip install` outside a venv, `cargo install` with no `--root`): it changes the user's machine, and the next run tests whatever was left there.

Some installers write build files into the repo (`build/`, `*.egg-info`, `target/`). Ignored files do not count as a change; anything else fails the run with "scenarios modified the repo", so keep those paths in `.gitignore`.

Misuse cases per row: no args, bad flag, malformed input, missing config (first use), port in use, empty input.
Missing tool: preflight warns for the tools your scenarios name; report the scenario unrunnable.
