#!/bin/bash
# fixture: a Go module whose tests are declared by their name alone (`func TestAdd(t *testing.T)`) and skip from their
# body (`t.Skip`). The adapter format cannot describe either yet (docs/mech-review-ci.md, Keys: "Tests declared by their
# name alone (Go ...) cannot be described yet"), so R0 cannot pass: the run should end with no commit on any branch
# and a report naming the cheats or controls R0 missed, never a setup PR (#23). The grader support is
# ci-doctor-setup-java's; only its new-commits and main lines matter here.
set -e
here="$(cd "$(dirname "$0")" && pwd -P)"
git init -q -b main .; git config user.email t@t; git config user.name t
printf '.gitconfig\n.config/\n.npm/\n.cache/\n' >> .git/info/exclude  # sandbox HOME files: not the work
printf 'module example.com/calc\n\ngo 1.22\n' > go.mod
cat > calc.go <<'GO'
package calc

func Add(a, b int) int { return a + b }

func Sub(a, b int) int { return a - b }
GO
cat > calc_test.go <<'GO'
package calc

import "testing"

func TestAdd(t *testing.T) {
	if got := Add(1, 2); got != 3 {
		t.Fatalf("Add(1, 2) = %d, want 3", got)
	}
}

func TestSub(t *testing.T) {
	if testing.Short() {
		t.Skip("slow")
	}
	if got := Sub(3, 2); got != 1 {
		t.Errorf("Sub(3, 2) = %d, want 1", got)
	}
}
GO
git add -A; git commit -qm "calc: go module"
source "$here/../ci-doctor-setup-java/arm.sh"
arm_verdict '{"status": "current", "folder": ".", "target_os": "linux", "ci": "write",
  "tests": ["TestAdd", "TestSub"], "test_files": ["calc_test.go"], "test_paths": "*_test.go"}'
