# ADR 0002: Python Backend with Bundled Runtime

## Status
Accepted

## Context
The Maid needs a backend orchestrator for ML/vision workloads. The spec lists "Python or Rust."

## Decision
Use **Python** as the backend orchestrator, bundled with a portable runtime (PyInstaller or python-build-standalone). All complexity hidden from the user — single installer, one-click setup.

## Rationale
- ML/vision ecosystem (insightface, dlib, PyMuPDF, python-docx, transformers) is overwhelmingly Python-native
- Faster MVP development — get to product-market fit quicker
- Rust port can happen in v2 if binary size becomes a constraint
- User experience priority: easy install, no manual dependency setup
- Face recognition, PDF parsing, and ExifTool integration have mature Python libraries

## Trade-offs
- Binary size: ~150MB+ vs Rust's ~30-50MB
- Memory usage: Python runtime overhead
- But: user doesn't care about binary size if it solves their problem

## Consequences
- Tauri spawns Python as a **managed sidecar process** via `tauri::command` + `std::process::Command`.
- Communication uses **Tauri's event system** (`emit` / `listen`) for real-time progress updates. No HTTP ports, no stdin parsing.
- Python process lifecycle is managed by Rust — auto-restart on crash, clean shutdown on app exit.
- Future optimization path: rewrite hot paths in Rust, keep Python for ML.
