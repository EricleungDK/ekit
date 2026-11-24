"""parser-install (#27's install step): the argvs that install the parser the base branch's adapter file declares.

The workflow runs them in order, as argv (never through a shell), in each job whose engine call reads source with the
adapter: guard (R2, R0) and red-first (R1 and R4 name the changed tests). The adapter file is the one r2 reads: at
--base, found by stack_plan.repo_adapter_at (the plan entry's file for the stack and folder, else
.ekit/adapters/<stack>.toml). The head's copy is never read, so a PR cannot install a package of its own (ADR 0001).
Prints {"stack", "adapter", "steps", "program"}: steps is a list of argv lists (parser_cmd.install_steps), empty for
a built-in, a stack with no adapter file, or a file with no [parser]; program is where the parser is after them
(parser_cmd.program_path), else null. Exit 0; 2 for usage, a git error or a base adapter file that does not read."""
import argparse
import json
import os
import sys

from . import adapter_file, data_adapter, gitio, parser_cmd, stack_plan


def steps(repo, base, stack, folder, at):
    """{stack, adapter, steps, program} of the stack's adapter file at the commit base, its prefixes under at."""
    adapter, path = stack_plan.repo_adapter_at(repo, base, stack, folder)
    if not isinstance(adapter, data_adapter.ParserAdapter):
        return {"stack": stack, "adapter": path, "steps": [], "program": None}
    return {"stack": stack, "adapter": path, "steps": parser_cmd.install_steps(adapter.parser, at),
            "program": parser_cmd.program_path(adapter.parser, at)}


def main(argv, dir_arg):
    """the subcommand: dir_arg is the CLI's --project-dir rule (under the repo root)."""
    # no help text of its own, as resolve (#29): the main --help describes parser-install
    p = argparse.ArgumentParser(prog="mech-review.py parser-install")
    p.add_argument("--repo", default=".")
    p.add_argument("--base", required=True)  # the adapter file is read there, never at head
    p.add_argument("--stack", required=True)
    p.add_argument("--project-dir", type=dir_arg, default=".")
    p.add_argument("--home")  # the dir the parser prefixes sit under: default parser_cmd.home(); absolute
    args = p.parse_args(argv)
    at = args.home or parser_cmd.home()
    if not os.path.isabs(at):
        print(f"mech-review: parser home `{at}`: want an absolute path", file=sys.stderr)
        return 2
    try:
        out = steps(args.repo, gitio.resolve(args.repo, args.base), args.stack, args.project_dir, at)
    except (gitio.Die, adapter_file.AdapterFileError) as e:
        print(f"mech-review: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out))
    return 0
