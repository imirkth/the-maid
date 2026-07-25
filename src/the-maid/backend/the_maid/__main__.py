"""CLI entry point for The Maid backend."""
from .api import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9473)
