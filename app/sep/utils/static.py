"""Define utilities regarding static files."""

from fastapi import HTTPException, Request
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from app.api.deps import get_current_user as get_current_user_api
from app.api.deps import oauth2_scheme
from app.sep.deps import get_current_user


class AuthenticatedStaticFiles(StaticFiles):
    """Define a StaticFiles subclass that enforces authentication."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process a request and serve static files ensuring authentication.

        Overrides :py:meth:`starlette.staticfiles.StaticFiles.__call__` to ensure the
        user is authenticated through the `Authorization` header or an auth cookie.

        :param scope: The ASGI connection scope containing request information.
        :type scope: starlette.types.Scope
        :param receive: An asynchronous callable to receive ASGI messages.
        :type receive: starlette.types.Receive
        :param send: An asynchronous callable to send ASGI messages.
        :type send: starlette.types.Send
        :raises HTTPException: Raised if the request is not authenticated.
        """
        if scope["type"] == "http":
            request = Request(scope, receive, send)
            try:
                token = await oauth2_scheme(request)
                await get_current_user_api(token)
            except HTTPException:
                await get_current_user(request)
        await super().__call__(scope, receive, send)
