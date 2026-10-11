from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class WorkspaceCoordinator:
    """Serializes workspace access across lead, subagents, teammates and background jobs."""

    def __init__(self):
        self._lock = threading.RLock()
        self._meta_lock = threading.Lock()
        self.active_actor: str | None = None
        self.active_operation: str | None = None
        self.waiting = 0

    @contextmanager
    def access(self, actor: str, operation: str):
        with self._meta_lock:
            self.waiting += 1
        started = time.monotonic()
        self._lock.acquire()
        with self._meta_lock:
            self.waiting -= 1
            self.active_actor = actor
            self.active_operation = operation
        try:
            yield time.monotonic() - started
        finally:
            with self._meta_lock:
                self.active_actor = None
                self.active_operation = None
            self._lock.release()

    def snapshot(self) -> dict:
        with self._meta_lock:
            return {"actor": self.active_actor, "operation": self.active_operation, "waiting": self.waiting}

