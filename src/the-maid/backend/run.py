#!/usr/bin/env python3
"""
The Maid — Python Backend Entry Point
Starts FastAPI server on port 9473 for Tauri IPC.
"""

import uvicorn
from the_maid.api import app

if __name__ == "__main__":
    print("READY", flush=True)
    print("🧹 [The Maid] Python backend ready", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=9473, log_level="info")
