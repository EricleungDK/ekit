---
type: regex
target: {source: file, path: .git/ekit/results.json}
pattern: '"filter": null[\s\S]*"id": "add-task"[\s\S]*"id": "finish-task"[\s\S]*"id": "list-tasks"'
arm: both
---
