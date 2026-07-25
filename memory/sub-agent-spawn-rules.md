# Sub-Agent Spawn Rules

Templates for spawning sub-agents consistently across The Maid project.

## Default Coding Sub-Agent

For implementing slices and writing code:

- **Model:** `glm-5.2:cloud`
- **Skills:** `/implement` + `/ponytail -full`
- **Context fork:** Yes (needs current codebase state)
- **Timeout:** 3600s (60 min)
- **Must complete:** Implementation + tests passing before reporting done
- **Must include in task prompt:** Explicit reference to both skills by name, plus the full skill.md contents pasted in context (agents don't have access to skill files unless we paste them)

## Auditor Sub-Agent

For auditing code quality and over-engineering:

- **Model:** `kimi-k2.7-code:cloud`
- **Skill:** `/ponytail-audit`
- **Context fork:** Yes (needs full repo state)
- **Timeout:** 3600s
- **Output:** GitHub issue comment or new issue #14
- **Scope:** Over-engineering only. Correctness/bugs are separate reviews.

## Fix Sub-Agent

For fixing audit findings or bugs:

- **Model:** `glm-5.2:cloud`
- **Skills:** `/implement` + `/ponytail -full`
- **Context fork:** Yes
- **Timeout:** 3600s
- **Must complete:** Fix all items + tests passing
- **Must include in task prompt:** Explicit reference to both skills by name, plus the full skill.md contents pasted in context

## Tester Sub-Agent

For reviewing code for bugs, mishandled cases, and edge cases:

- **Model:** `kimi-k2.7-code:cloud`
- **Skill:** `/diagnosing-bugs`
- **Context fork:** Yes (needs full codebase state)
- **Timeout:** 3600s
- **Output:** GitHub issue comment with ranked findings
- **Scope:** Correctness bugs, mishandled cases, missing edge cases, error handling gaps. NOT over-engineering (that's the auditor).
- **Must do:** Build a feedback loop, reproduce, minimize, hypothesize, instrument, fix, write regression test. Follow all 6 phases of the diagnosing-bugs skill.

## White-Hat 1 Sub-Agent

For security auditing (first opinion):

- **Model:** `kimi-k2.7-code:cloud`
- **Skill:** `/white-hat`
- **Context fork:** Yes (needs full codebase state)
- **Timeout:** 3600s
- **Output:** GitHub issue comment with severity-ranked findings
- **Scope:** Dependency CVEs, secrets leakage, input validation, auth/authz, infrastructure, logging, data protection. Build attack chains, not isolated findings.
- **Must do:** Follow all 8 workflow steps (scope → recon → scan → manual review → chain analysis → report → prioritize → re-test). Report by severity: Critical, High, Medium, Low, Info.

## White-Hat 2 Sub-Agent

For security auditing (second opinion, different model perspective):

- **Model:** `glm-5.2:cloud`
- **Skill:** `/white-hat`
- **Context fork:** Yes (needs full codebase state)
- **Timeout:** 3600s
- **Output:** GitHub issue comment with severity-ranked findings
- **Scope:** Same as White-Hat 1 but independent review. Cross-reference findings with WH1 for consensus.
- **Must do:** Same workflow as White-Hat 1. Independent analysis — don't just repeat WH1 findings, find what they missed.

## Quick Reference

| Type | Model | Skills | Timeout | Notes |
|------|-------|--------|---------|-------|
| Coding | glm-5.2:cloud | /implement + /ponytail-full | 60m | Tests must pass |
| Audit | kimi-k2.7-code:cloud | /ponytail-audit | 60m | Post to GitHub |
| Fix | glm-5.2:cloud | /implement + /ponytail-full | 60m | Address all findings |
| Tester | kimi-k2.7-code:cloud | /diagnosing-bugs | 60m | Bugs & edge cases |
| White-Hat 1 | kimi-k2.7-code:cloud | /white-hat | 60m | Security audit |
| White-Hat 2 | glm-5.2:cloud | /white-hat | 60m | Security audit (2nd opinion) |

## Custom Personas

Imirk can override any field per spawn request:
- Different model (e.g., `claude-sonnet-4-20250514`)
- Different skill (e.g., `/tdd` instead of `/implement`)
- Different rules (e.g., "no tests needed" for prototype spikes)
- Different output target (e.g., Discord message instead of GitHub issue)
- Different timeout (default is 60 min)

When Imirk asks for a custom persona, update this file with the new template.