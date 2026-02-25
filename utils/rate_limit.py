"""
BUG-8 FIX: Simple in-memory rate limiter for local single-user tool.

Limits requests per path-prefix to prevent accidental request storms
(e.g. runaway scripts or UI bugs sending rapid-fire POSTs).
"""
import time
from collections import defaultdict

from fastapi import HTTPException, Request


class RateLimiter:
    """
    Simple token-bucket rate limiter keyed by client IP + path prefix.

    Parameters:
        max_requests: Maximum number of requests in the window.
        window_seconds: Time window in seconds.
    """

    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # key -> list of request timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, key: str) -> None:
        """Remove timestamps outside the current window."""
        cutoff = time.monotonic() - self.window_seconds
        self._requests[key] = [
            t for t in self._requests[key] if t > cutoff
        ]

    def check(self, key: str) -> None:
        """
        Check rate limit for the given key.
        Raises HTTPException(429) if limit is exceeded.
        """
        self._cleanup(key)
        if len(self._requests[key]) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Zu viele Anfragen. Maximal {self.max_requests} "
                    f"Requests pro {self.window_seconds:.0f} Sekunden erlaubt."
                ),
            )
        self._requests[key].append(time.monotonic())


# Shared instance: 10 requests per 60 seconds for expensive triage operations
triage_rate_limiter = RateLimiter(max_requests=10, window_seconds=60.0)

# Shared instance: 10 requests per 30 seconds for undo operations
undo_rate_limiter = RateLimiter(max_requests=10, window_seconds=30.0)


async def check_triage_rate_limit(request: Request) -> None:
    """FastAPI dependency to check rate limit on triage endpoints."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{request.url.path}"
    triage_rate_limiter.check(key)


async def check_undo_rate_limit(request: Request) -> None:
    """FastAPI dependency to check rate limit on undo endpoints."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:undo"
    undo_rate_limiter.check(key)
