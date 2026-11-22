---
type: regex
target: {source: file, path: .ekit/stack-plan.toml}
# a [[stack]] table named for TypeScript, adapter ts, status current or planned (keys in any order)
pattern: '\[\[stack\]\](?=(?:(?!\[\[)[\s\S])*?name\s*=\s*["''][^"''\n]*(?:ts|TS|[Tt]ype[Ss]cript)[^"''\n]*["''])(?=(?:(?!\[\[)[\s\S])*?status\s*=\s*["''](?:current|planned)["''])(?=(?:(?!\[\[)[\s\S])*?adapter\s*=\s*["'']ts["''])'
arm: both
---
