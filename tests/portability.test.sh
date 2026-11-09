#!/bin/bash
# Other harnesses (Codex, Copilot, skills.sh) read .claude-plugin/ and copy skills without hooks or scripts.
# What can be checked offline is that the manifests, the files they point at and the README agree. That the
# install commands work in each harness is not checked here: it needs those CLIs.
source "$(dirname "$0")/lib.sh"
j() { python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."):
    d = d[int(k)] if k.isdigit() else d.get(k, "")
print("\n".join(sorted(d)) if isinstance(d, list) else d)' "$ROOT/.claude-plugin/$1" "$2"; }

listed="$(j plugin.json skills)"
dirs="$(cd "$ROOT" && for d in skills/*/; do echo "./${d%/}"; done | sort)"
eq "$listed" "$dirs" "plugin.json skills array = skills/*/"
eq "$(j plugin.json repository)" "https://github.com/EricleungDK/ekit" "plugin.json repository"
[[ "$(j plugin.json version)" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && ok "plugin.json version is MAJOR.MINOR.PATCH" || fail "plugin.json version is MAJOR.MINOR.PATCH"
[[ -n "$(j plugin.json license)" && -f $ROOT/LICENSE ]] && ok "plugin.json names a license and LICENSE exists" || fail "plugin.json names a license and LICENSE exists"

# each skill: the directory name is the skill's name (what every harness installs it as)
for d in "$ROOT"/skills/*/; do
  name="$(basename "$d")"
  eq "$(sed -n 's/^name: //p' "$d/SKILL.md" | head -1)" "$name" "skill $name: frontmatter name = directory"
  # relative links in a skill resolve inside its own directory: a harness that copies one skill copies no sibling
  for l in $(grep -o '](\([^)#]*\))' "$d/SKILL.md" | sed 's/](\(.*\))/\1/'); do
    [[ $l == http* ]] || { [[ -f $d/$l ]] && ok "skill $name: link $l resolves" || fail "skill $name: link $l resolves"; }
  done
done

# the marketplace entry is this plugin; the README's install line is built from the two names
plugin="$(j plugin.json name)"; market="$(j marketplace.json name)"
eq "$(j marketplace.json plugins.0.name)" "$plugin" "marketplace lists the plugin under its own name"
eq "$(j marketplace.json plugins.0.source)" "./" "marketplace source is the repo root"
readme="$(cat "$ROOT/README.md")"
for cli in claude copilot; do has "$readme" "$cli plugin install $plugin@$market" "README: $cli install uses $plugin@$market"; done
has "$readme" "codex plugin add $plugin@$market" "README: codex install uses $plugin@$market"

# every hook command runs a script that ships
while IFS= read -r script; do
  [[ -f $ROOT/$script ]] && ok "hook script $script exists" || fail "hook script $script exists"
done < <(grep -o 'CLAUDE_PLUGIN_ROOT}/[^\\"]*' "$ROOT/hooks/hooks.json" | sed 's/^CLAUDE_PLUGIN_ROOT}\///' | sort -u)

# A skill that needs kit scripts must work with no SessionStart hook (no `[ekit] Scenario runner:` line).
for f in $(grep -l '<kit>' "$ROOT"/skills/*/SKILL.md); do
  has "$(cat "$f")" '~/.ekit' "$(basename "$(dirname "$f")"): <kit> falls back to ~/.ekit"
done
done_tests
