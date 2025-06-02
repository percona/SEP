"""Define middleware to manage temporary messages stored in cookies."""

import json
import logging
from collections import OrderedDict
from enum import IntEnum
from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

__all__ = [
    "Message",
    "MessageLevel",
    "MessagesMiddleware",
    "add_message",
    "error",
    "get_messages",
    "info",
    "success",
    "warning",
]

from app.core.security import crypto_serializer
from app.core.utils import json_serializer
from app.core.utils.fields import RequiredStr

logger = logging.getLogger(__name__)


class MessageLevel(IntEnum):
    """Enumerate the possible message levels.

    :cvar INFO: Represents a standard information message.
    :vartype INFO: int
    :cvar SUCCESS: Represents a success message.
    :vartype SUCCESS: int
    :cvar WARNING: Represents a warning message.
    :vartype WARNING: int
    :cvar ERROR: Represents an error message.
    :vartype ERROR: int
    """

    INFO = 1
    SUCCESS = 3
    WARNING = 5
    ERROR = 7


class Message(BaseModel):
    """Represent a user-facing message to be displayed in the UI.

    :param level: The level of the message.
    :type level: MessageLevel
    :param text: The content of the message. Must not exceed 512 characters.
    :type text: str
    :param sticky: A flag indicating whether the message should persist until dismissed.
    :type sticky: bool
    """

    model_config = ConfigDict(populate_by_name=True)
    level: MessageLevel = Field(alias="l")
    text: RequiredStr = Field(alias="t", max_length=512)
    sticky: bool = Field(default=False, exclude=True)

    def __hash__(self) -> int:
        """Return a hash of the message based on its level and text.

        This method allows Message objects to be used in sets or as dictionary keys.

        :return: A hash value for the message.
        :rtype: int
        """
        return hash((self.level, self.text, self.sticky))

    @model_validator(mode="before")
    @classmethod
    def set_sticky_from_level(cls, data: Any) -> Any:
        """Pre-process input data to set the 'sticky' flag based on the message level.

        This method allows validation for messages serialized with the `serialize_level`
        serializer, in which the `sticky` attribute is defined in the `level` by adding
        1 to the value.

        :param data: The raw data to be validated, typically a dictionary.
        :type data: Any
        :return: The processed data with a potentially updated 'sticky' attribute.
        :rtype: Any
        """
        if isinstance(data, dict) and "sticky" not in data:
            level = data.get("l")
            if isinstance(level, int) and not level % 2:
                data["l"] -= 1
                data["sticky"] = True
        return data

    @field_serializer("level")
    def serialize_level(self, level: MessageLevel) -> int:
        """Serialize the message level by incorporating the sticky flag.

        In order to minimize the messages cookie, the `sticky` attribute is defined
        in the `level` by adding 1 to the original `level` value.

        :param level: The original message level.
        :type level: MessageLevel
        :return: The serialized level as an integer, plus 1 if `sticky` is True.
        :rtype: int
        """
        return level + self.sticky


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
            request.state.messages = OrderedDict.fromkeys(
                Message.model_validate(msg)
                for msg in json.loads(crypto_serializer.loads(old_cookie))
            )

        response = await call_next(request)
        while (
            len(
                new_cookie := crypto_serializer.dumps(
                    json_serializer(list(request.state.messages), separators=(",", ":"))
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


def add_message(
    request: Request, level: MessageLevel, text: str, *, sticky: bool = False
) -> None:
    """Add a message to the current request's message queue.

    This function creates a new Message object with the provided level, text, and
    sticky flag and appends it to the `messages` list in the request state. If the
    request state does not support messages, an exception is logged.

    :param request: The HTTP request object.
    :type request: Request
    :param level: The level of the message.
    :type level: MessageLevel
    :param text: The text content of the message.
    :type text: str
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    :raises AttributeError: If the request does not have a messages attribute.
    :raises ValueError: If the message data is invalid and fails validation.
    """
    try:
        message = Message(level=level, text=text, sticky=sticky)
        request.state.messages[message] = None
    except AttributeError:
        logger.exception("Unable to add messages without MessageMiddleware")
    except ValueError:
        logger.exception("Error building Message object")
    else:
        logger.debug("Sending message to %s: %s", request.client.host, message)


def get_messages(request: Request, max_qty: int | None = None) -> list[Message]:
    """Retrieve and remove messages from the request state.

    This function fetches messages stored in the request state (up to `max_qty` if
    specified), removes them from the state, and returns them as a list.

    :param request: The HTTP request object.
    :type request: Request
    :param max_qty: Optional maximum number of messages to retrieve. If None (default),
        all messages are returned.
    :type max_qty: int | None
    :return: A list of Message objects.
    :rtype: list[Message]
    """
    messages = []
    saved_messages = getattr(request.state, "messages", None)
    while saved_messages and (max_qty is None or len(messages) < max_qty):
        message, _ = saved_messages.popitem(last=False)
        messages.append(message)
    return messages


def info(request: Request, text: str, *, sticky: bool = False) -> None:
    """Add an informational message to the request's message queue.

    This is a convenience function that adds a message with the INFO level.

    :param request: The HTTP request object.
    :type request: Request
    :param text: The informational message text.
    :type text: str
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    """
    add_message(request, MessageLevel.INFO, text, sticky=sticky)


def success(request: Request, text: str, *, sticky: bool = False) -> None:
    """Add a success message to the request's message queue.

    This is a convenience function that adds a message with the SUCCESS level.

    :param request: The HTTP request object.
    :type request: Request
    :param text: The success message text.
    :type text: str
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    """
    add_message(request, MessageLevel.SUCCESS, text, sticky=sticky)


def warning(request: Request, text: str, *, sticky: bool = False) -> None:
    """Add a warning message to the request's message queue.

    This is a convenience function that adds a message with the WARNING level.

    :param request: The HTTP request object.
    :type request: Request
    :param text: The warning message text.
    :type text: str
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    """
    add_message(request, MessageLevel.WARNING, text, sticky=sticky)


def error(request: Request, text: str, *, sticky: bool = False) -> None:
    """Add an error message to the request's message queue.

    This is a convenience function that adds a message with the ERROR level.

    :param request: The HTTP request object.
    :type request: Request
    :param text: The error message text.
    :type text: str
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    """
    add_message(request, MessageLevel.ERROR, text, sticky=sticky)
