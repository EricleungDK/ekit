# Sourced by the scaffolds that write a verdict script (stack-plan-js-to-ts/setup.sh, ci-doctor-setup-java/arm.sh,
# ci-doctor-repair-java-runner/arm.sh). copy_engine DIR: the kit's engine (scripts/, no bytecode, and the plugin
# manifest its report reads the version from) copied into DIR, so the verdict reads only the scaffold's .git/ekit-eval/:
# the eval sandbox denies the agent's commands (and the verdict the git shim runs among them) the kit's evals/ with
# the plugin, and the whole kit without it.
copy_engine() {
  local kit
  kit="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
  python3 -I - "$kit" "$1" <<'PY'
import os, shutil, sys
kit, dest = sys.argv[1:3]
shutil.copytree(os.path.join(kit, "scripts"), os.path.join(dest, "scripts"),
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
os.makedirs(os.path.join(dest, ".claude-plugin"), exist_ok=True)
shutil.copy2(os.path.join(kit, ".claude-plugin", "plugin.json"), os.path.join(dest, ".claude-plugin", "plugin.json"))
PY
}
