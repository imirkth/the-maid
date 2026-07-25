# Domain Docs

The Maid uses a **single-context** domain model.

## Layout

```
/
├── CONTEXT.md              ← domain glossary (terms, definitions)
├── docs/
│   └── adr/
│       └── NNNN-title.md   ← architecture decision records
└── src/
```

## Rules

- `CONTEXT.md` is strictly a glossary — no implementation details, no specs, no scratch notes.
- ADRs are created sparingly: only when a decision is hard to reverse, surprising without context, and the result of a real trade-off.
- Skills read `CONTEXT.md` before touching code to respect domain language.
