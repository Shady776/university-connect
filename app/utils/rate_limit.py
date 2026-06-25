"""
Shared rate limiter, built on slowapi (a thin wrapper around the
`limits` library) so every route in the app uses the same limiter
instance and the same exception handler.

Usage in a route file:

    from fastapi import Request
    from ..utils.rate_limit import limiter

    @router.post("/login")
    @limiter.limit("5/minute")
    def login(request: Request, ...):
        ...

Notes:
- The decorated function MUST accept a `request: Request` parameter —
  slowapi reads `request.app.state.limiter` to enforce the limit.
- Limits are keyed by client IP by default (get_remote_address). If this
  app sits behind a proxy/load balancer (Railway does proxy requests),
  make sure `X-Forwarded-For` is trusted so the real client IP is used
  rather than the proxy's IP for every request.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)