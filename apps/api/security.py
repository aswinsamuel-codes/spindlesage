"""HTTP hardening for the API: headers, body-size limit, failed-auth throttling.

API keys are 256-bit random values, so guessing one is not a practical attack;
the throttle exists to limit noise and slow scripted misuse, and failed
attempts are logged (client address and path only, never the key).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("spindlesage.security")

MAX_BODY_BYTES = 1024 * 1024

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# The dashboard is a static, same-origin bundle: no inline scripts, no third parties.
DASHBOARD_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'; object-src 'none'"
)


class FailedAuthThrottle:
    """Sliding-window count of failed authentications per client address."""

    def __init__(self, limit: int = 20, window_s: float = 60.0, clock=time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, client: str, now: float) -> deque[float]:
        events = self._failures[client]
        while events and now - events[0] > self.window_s:
            events.popleft()
        return events

    def blocked(self, client: str) -> bool:
        with self._lock:
            return len(self._prune(client, self.clock())) >= self.limit

    def record_failure(self, client: str) -> None:
        with self._lock:
            now = self.clock()
            self._prune(client, now).append(now)


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, throttle: FailedAuthThrottle, max_body_bytes: int = MAX_BODY_BYTES):
        super().__init__(app)
        self.throttle = throttle
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next) -> Response:
        client = request.client.host if request.client else "unknown"

        if self.throttle.blocked(client):
            response: Response = JSONResponse(
                {"detail": "Too many failed authentication attempts; try again later"},
                status_code=429,
                headers={"Retry-After": str(int(self.throttle.window_s))},
            )
        elif self._too_large(request):
            response = JSONResponse({"detail": "Request body too large"}, status_code=413)
        else:
            response = await call_next(request)
            if response.status_code == 401:
                self.throttle.record_failure(client)
                log.warning("Failed authentication from %s for %s", client, request.url.path)

        for name, value in BASE_HEADERS.items():
            response.headers.setdefault(name, value)
        path = request.url.path
        if path.startswith("/dashboard"):
            response.headers["Content-Security-Policy"] = DASHBOARD_CSP
        elif not path.startswith(("/docs", "/redoc", "/openapi.json")):
            # Data responses may contain operational details: never cache them.
            response.headers["Cache-Control"] = "no-store"
        return response

    def _too_large(self, request: Request) -> bool:
        length = request.headers.get("content-length")
        try:
            return length is not None and int(length) > self.max_body_bytes
        except ValueError:
            return True
