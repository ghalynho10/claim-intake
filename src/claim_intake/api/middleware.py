"""Request id middleware (pure ASGI).

Accepts an inbound `X-Request-ID` only if it is 1 to 64 letters, digits or
hyphens; otherwise generates one. The id lives in a contextvar for the whole
request (Starlette copies context into the sync thread pool, so sync endpoints
see it too) and is echoed in the response header.
"""

import re
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from claim_intake.logging import request_id_var

HEADER = "X-Request-ID"
_VALID_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = Headers(scope=scope).get(HEADER)
        request_id = inbound if inbound and _VALID_ID.fullmatch(inbound) else uuid4().hex

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)
