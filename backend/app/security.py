"""Demo-grade API protections: server-side fetch guard + per-IP rate limit.

- is_safe_fetch_url(): blocks cloud-metadata and private targets when the
  backend fetches a caller-supplied URL (cutout, PDF cover). Loopback stays
  allowed (the frontend serves demo assets on localhost:3000).
- RateLimitMiddleware: caps billed-endpoint abuse on shared server keys.
  Callers with their own key (BYOK headers) pay their own way and bypass it.
"""

import ipaddress
import logging
import os
import socket
import time
import urllib.parse
from collections import deque
from typing import Deque, Dict

from starlette.middleware.base import BaseHTTPMiddleware  # type: ignore
from starlette.requests import Request  # type: ignore
from starlette.responses import JSONResponse  # type: ignore

logger = logging.getLogger(__name__)

RATE_LIMIT_ENV = "RATE_LIMIT_PER_MIN"
RATE_LIMIT_DEFAULT = 120
RATE_LIMIT_WINDOW_SEC = 60.0


def _resolved_ips(host: str) -> list:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return [info[4][0] for info in infos]


def is_safe_fetch_url(url: str) -> bool:
    """True when the backend may fetch this caller-supplied URL. Never raises."""
    try:
        parts = urllib.parse.urlparse(url or "")
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        host = parts.hostname
        if host == "localhost":
            return True
        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError:
            ips = []
            for raw in _resolved_ips(host):
                try:
                    ips.append(ipaddress.ip_address(raw))
                except ValueError:
                    return False
            if not ips:
                return False
        for ip in ips:
            if ip.is_loopback:
                continue
            if ip.is_private or ip.is_reserved or ip.is_link_local or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def _limit_per_min() -> int:
    try:
        return max(1, int(os.getenv(RATE_LIMIT_ENV, str(RATE_LIMIT_DEFAULT))))
    except ValueError:
        return RATE_LIMIT_DEFAULT


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window cap on POST /api/v1/* per client IP (in-memory)."""

    def __init__(self, app):
        super().__init__(app)
        self._hits: Dict[str, Deque[float]] = {}

    async def dispatch(self, request: Request, call_next):
        if (
            request.method == "POST"
            and request.url.path.startswith("/api/v1/")
            and "authorization" not in request.headers
            and "x-replicate-key" not in request.headers
        ):
            now = time.monotonic()
            key = request.client.host if request.client else "unknown"
            window = self._hits.setdefault(key, deque())
            cutoff = now - RATE_LIMIT_WINDOW_SEC
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= _limit_per_min():
                logger.warning("Rate limit hit for %s.", key)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Trop de requêtes : réessayez dans une minute."},
                )
            window.append(now)
        return await call_next(request)


__all__ = ["is_safe_fetch_url", "RateLimitMiddleware"]
