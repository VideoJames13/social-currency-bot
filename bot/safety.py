"""Guards against the bot misbehaving: a posting circuit breaker."""

from collections import deque
from datetime import datetime, timedelta


class PostGuard:
    """Allows at most `limit` channel posts per rolling `window`. Once the limit is hit,
    posting pauses until the window has room again (no manual reset needed)."""

    def __init__(self, limit: int, window: timedelta = timedelta(hours=1)):
        self.limit = limit
        self.window = window
        self._sent: deque[datetime] = deque()
        self.tripped = False   # True while paused; flips back when posting resumes

    def _prune(self, now: datetime) -> None:
        while self._sent and self._sent[0] <= now - self.window:
            self._sent.popleft()

    def allow(self, now: datetime) -> bool:
        """Record and allow a post, or return False if paused."""
        self._prune(now)
        if len(self._sent) >= self.limit:
            self.tripped = True
            return False
        self.tripped = False
        self._sent.append(now)
        return True

    def resumes_at(self) -> datetime | None:
        return self._sent[0] + self.window if self._sent else None
