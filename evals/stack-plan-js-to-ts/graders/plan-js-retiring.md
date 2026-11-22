---
type: regex
target: {source: file, path: .ekit/stack-plan.toml}
# the `js` [[stack]] table is still there, now retiring (keys in any order)
pattern: '\[\[stack\]\](?=(?:(?!\[\[)[\s\S])*?name\s*=\s*["'']js["''])(?=(?:(?!\[\[)[\s\S])*?status\s*=\s*["'']retiring["''])'
arm: both
---
