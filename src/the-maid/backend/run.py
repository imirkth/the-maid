#!/usr/bin/env python3
"""
The Maid — Python Backend Entry Point
Starts FastAPI server on port 9473 for Tauri IPC.
"""

import socket

import uvicorn

from the_maid.api import app

HOST = "127.0.0.1"
PORT = 9473


def main() -> None:
    # Bind + listen BEFORE signalling READY, then hand the pre-bound socket to
    # uvicorn. Once listen() returns, the kernel queues connections even before
    # uvicorn accepts, so the Rust sidecar can never hit "connection refused"
    # after seeing READY. (uvicorn runs lifespan startup before binding its own
    # sockets, so printing READY in a startup hook would NOT be safe.)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(2048)

    print("READY", flush=True)
    print("🧹 [The Maid] Python backend ready", flush=True)

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info")
    uvicorn.Server(config).run(sockets=[sock])


if __name__ == "__main__":
    main()