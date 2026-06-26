# Copyright (C) 2026 Percona LLC
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

"""Define middleware to manage temporary messages stored in cookies."""

__all__ = ["MessagesMiddleware"]

import json
import logging
from collections import OrderedDict
from typing import ClassVar

from itsdangerous import BadPayload, BadSignature
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.security import crypto_serializer
from app.core.utils import json_serializer
from app.sep.middleware.messages.models import Message

logger = logging.getLogger("app.sep.middleware.messages")


class MessagesMiddleware(BaseHTTPMiddleware):
    """Manage temporary messages stored in cookies.

    This middleware retrieves messages stored in a cookie from the incoming request,
    attaches them to the request state, and updates the response to include a cookie
    with the current message queue. If the cookie size exceeds a maximum threshold,
    older messages are discarded.

    :cvar MAX_COOKIE_SIZE: Maximum allowed size (in bytes) for the messages cookie.
        Set to 1024.
    :vartype MAX_COOKIE_SIZE: int
    :cvar COOKIE_NAME: Name of the cookie used for storing messages. Set to "messages"
    :vartype COOKIE_NAME: str
    :cvar COOKIE_MAX_AGE: Maximum age (in seconds) for the messages cookie. Set to
        12 hours.
    :vartype COOKIE_MAX_AGE: int
    """

    MAX_COOKIE_SIZE: ClassVar[int] = 1024
    COOKIE_NAME: ClassVar[str] = "messages"
    COOKIE_MAX_AGE: ClassVar[int] = 60 * 60 * 12

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Retrieve messages from cookies and update the response.

        This method parses the cookie (if present) to restore a list of messages into
        the request state. After processing the request, it serializes any remaining
        messages back into a cookie, ensuring that the cookie does not exceed the
        maximum allowed size.

        :param request: The incoming HTTP request.
        :type request: Request
        :param call_next: The next callable in the middleware chain.
        :type call_next: RequestResponseEndpoint
        :return: The HTTP response with an updated messages cookie or with the cookie
            removed, in case no message is left in the queue.
        :rtype: Response
        """
        request.state.messages = OrderedDict()
        if old_cookie := request.cookies.get(self.COOKIE_NAME):
            try:
                request.state.messages = OrderedDict.fromkeys(
                    Message.model_validate(msg)
                    for msg in json.loads(crypto_serializer.loads(old_cookie))
                )
            except (BadSignature, BadPayload, json.JSONDecodeError, ValidationError):
                logger.debug("Invalid messages cookie; treating as empty")

        response = await call_next(request)
        while (
            len(
                new_cookie := crypto_serializer.dumps(
                    json_serializer(
                        list(request.state.messages),
                        encoders_kwargs={"exclude_none": True},
                        separators=(",", ":"),
                    )
                )
            )
            > self.MAX_COOKIE_SIZE
        ) and request.state.messages:
            discarded_msg, _ = request.state.messages.popitem(last=False)
            logger.debug("Discarding message %s for %s", discarded_msg, request.client)

        if request.state.messages:
            response.set_cookie(
                key=self.COOKIE_NAME,
                value=new_cookie,
                httponly=True,
                max_age=self.COOKIE_MAX_AGE,
            )
        else:
            response.delete_cookie(self.COOKIE_NAME)

        return response
