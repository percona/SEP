# Copyright 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

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
