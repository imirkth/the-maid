# Triage Labels

The Maid uses the default canonical triage roles. Each issue carries exactly one category role and one state role.

## Category Roles

- `bug` — something is broken
- `enhancement` — new feature or improvement

## State Roles

- `needs-triage` — maintainer needs to evaluate
- `needs-info` — waiting on reporter for more information
- `ready-for-agent` — fully specified, ready for an AFK agent
- `ready-for-human` — needs human implementation
- `wontfix` — will not be actioned

## Label Strings

Since we use a local markdown tracker, labels are stored in the frontmatter `labels:` field of each issue file. The strings above are used verbatim.
