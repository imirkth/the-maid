# ADR 0003: Model Distribution — Hybrid Tier (Bundled Text LLM + Face, Vision On-Demand)

## Status
Accepted

## Context
The Maid embeds models locally. Need to decide what ships in the installer vs downloads on-demand.

## Decision
**Option A — Hybrid tier:**
- **Bundled:** Text LLM (1B params, ~500MB) + Face models (RetinaFace + ArcFace, ~100MB) = ~600MB installer
- **Download on-demand:** Vision model (OCR, ~500MB–1GB) — optional "Premium" download

## Rationale
- Face clustering is a headline feature — users expect it to work out of the box
- Receipt/document OCR (vision) is a nice-to-have that can download later
- Core file organization works offline immediately with bundled text LLM
- ~600MB is manageable for a one-time download; 1.5GB+ (all models) is painful
- Face recognition runs in a rigid, optimized pipeline — model weights are small (~100MB)

## Trade-offs
- Offline users can't use OCR until they download vision model
- Need a model manager UI (download progress, storage used)

## Consequences
- Installer size: ~600MB
- Need "Models" settings panel for on-demand downloads
- Face clustering works immediately after install
- OCR/receipt scanning gated behind download

## Future
If LLM sizes drop (e.g., 0.5B param models with good quality), revisit bundling vision too.
