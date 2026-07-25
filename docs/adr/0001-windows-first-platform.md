# ADR 0001: Windows-First Platform Strategy

## Status
Accepted

## Context
The Maid targets desktop users with messy file systems. We need to choose a primary platform for v1.

## Decision
Start with **Windows** as the primary platform for v1.

## Rationale
- Windows has straightforward filesystem access (no macOS sandboxing/iCloud abstraction layers)
- The "Desktop of Doom" problem is universal, but Windows users represent the largest desktop market
- macOS photos are often locked behind iCloud/Photos.app APIs, complicating face clustering
- We can port to macOS/Linux once v1 is validated

## Consequences
- Tauri supports Windows natively (no extra work)
- Face recognition pipeline can scan any image on disk without sandbox restrictions
- Need Windows code signing for distribution (Certum/SSL.com ~$200/yr)
- **Installer: NSIS** — Tauri-integrated, scriptable wizard for folder/feature/model selection during install
- macOS users wait for v2
