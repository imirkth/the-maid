# Issue Tracker

The Maid uses a **local markdown issue tracker**.

## How it works

Issues live as markdown files under `.scratch/` in the repo root:

```
.scratch/
├── feature-name/
│   ├── 001-description.md
│   └── 002-follow-up.md
└── bug-name/
    └── 001-report.md
```

Each issue is a self-contained markdown file with frontmatter:

```markdown
---
id: 001
title: "Feature description"
status: open | in-progress | done
created: YYYY-MM-DD
labels: [bug, enhancement, needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix]
---

## Problem
...

## Solution
...
```

## Creating issues

Use the `to-issues` skill or create files manually under `.scratch/<feature>/`.

## Triage

The `/triage` skill reads from `.scratch/` and moves issues through the state machine.

## PRs as request surface

No — PRs are not tracked as issues. External PRs are evaluated manually.
