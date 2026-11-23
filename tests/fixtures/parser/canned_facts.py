"""A stub parser command that knows nothing of any language (#27 review): it prints the facts written by hand for the
exact text it is given. `canned_facts.py DIR PATH`: stdin's text is looked up as DIR/<sha256 of the text>.json, printed
as it is; an unknown text exits 2. No ekit import: the facts are independent of ekit's own scanner."""
import hashlib
import os
import sys


def main(argv):
    text = sys.stdin.buffer.read()
    name = os.path.join(argv[0], hashlib.sha256(text).hexdigest() + ".json")
    if not os.path.exists(name):
        print(f"canned_facts: no facts for this text ({name})", file=sys.stderr)
        return 2
    with open(name, "rb") as f:
        sys.stdout.buffer.write(f.read())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
