"""Graceful shutdown state and signal handling."""

from __future__ import annotations

import signal


class ShutdownGuard:
    def __init__(self) -> None:
        self.draining = False
        self._previous: dict = {}

    def start_draining(self, signum=None, frame=None) -> None:
        self.draining = True
        previous = self._previous.get(signum)
        if callable(previous):
            previous(signum, frame)

    def arm(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._previous[sig] = signal.getsignal(sig)
            signal.signal(sig, self.start_draining)


shutdown_guard = ShutdownGuard()
