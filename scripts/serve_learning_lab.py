#!/usr/bin/env python3
"""Serve the Vision Lab field manual with the Python standard library only.

Usage:
    python3.11 scripts/serve_learning_lab.py
Then open http://127.0.0.1:4173/
"""

from __future__ import annotations

import functools
import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "learning"
PORT = 4173


def main() -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as server:
        print(f"Vision Lab field manual: http://127.0.0.1:{PORT}/")
        print(f"Root: {ROOT}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
