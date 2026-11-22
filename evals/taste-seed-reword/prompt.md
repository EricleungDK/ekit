---
max_turns: 40
allowed_tools: [Skill, Read, Bash, Edit, Write, Glob, Grep]
runs: 2
---

New app in this repo: a notes CLI (see README.md). No code yet, just my stories in `docs/stories.md`. Before any code, seed the taste-it scenarios from them, one per story, each scenario folder named after its story's id. Show me each proposal's wording. My answers are already here, apply them:

- `add-note`: approved.
- `share-note`: rejected. I'm dropping that feature.
- `export-notes`: reworded. The story becomes "As a user I can export my notes as a JSON file", and its check: after adding two notes, `python3 notes.py export out.json` writes `out.json` holding a JSON array of the two notes' texts.

Do not write the app itself. Tell me what you wrote, what became of each proposal, and how many features work.
