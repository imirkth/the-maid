# Sub-Agent Spawn Rules

Templates for spawning sub-agents consistently across The Maid project.

## Default Coding Sub-Agent

For implementing slices and writing code:

- **Model:** `glm-5.2:cloud`
- **Skills:** `/implement` + `/ponytail -full`
- **Context fork:** Yes (needs current codebase state)
- **Timeout:** 1800s (30 min)
- **Must complete:** Implementation + tests passing before reporting done

## Auditor Sub-Agent

For auditing code quality and over-engineering:

- **Model:** `kimi-k2.7-code:cloud`
- **Skill:** `/ponytail-audit`
- **Context fork:** Yes (needs full repo state)
- **Timeout:** 1800s
- **Output:** GitHub issue comment or new issue #14
- **Scope:** Over-engineering only. Correctness/bugs are separate reviews.

## Fix Sub-Agent

For fixing audit findings or bugs:

- **Model:** `glm-5.2:cloud`
- **Skills:** `/implement` + `/ponytail -full`
- **Context fork:** Yes
- **Timeout:** 1800s
- **Must complete:** Fix all items + tests passing

## Quick Reference

| Type | Model | Skills | Notes |
|------|-------|--------|-------|
| Coding | glm-5.2:cloud | /implement + /ponytail-full | Tests must pass |
| Audit | kimi-k2.7-code:cloud | /ponytail-audit | Post to GitHub |
| Fix | glm-5.2:cloud | /implement + /ponytail-full | Address all findings |

## Custom Personas

Imirk can override any field per spawn request:
- Different model (e.g., `claude-sonnet-4-20250514`)
- Different skill (e.g., `/tdd` instead of `/implement`)
- Different rules (e.g., "no tests needed" for prototype spikes)
- Different output target (e.g., Discord message instead of GitHub issue)

When Imirk asks for a custom persona, update this file with the new template.