"""Frozen entry point for the AstraCode desktop sidecar."""
from __future__ import annotations

import sys

from agent_harness.sidecar import run


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(run())
