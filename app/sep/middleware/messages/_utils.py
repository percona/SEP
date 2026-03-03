# Copyright 2025 Percona LLC
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

"""Define functions for creating and retrieving messages for the messages middleware."""

__all__ = [
    "add_message",
    "error",
    "from_validation_error",
    "get_messages",
    "info",
    "success",
    "warning",
]

import logging
from collections import OrderedDict
from collections.abc import Iterable

from pydantic import ValidationError
from starlette.requests import Request

from app.core.utils.pydantic import loc_to_dot_sep
from app.sep.middleware.messages.config import messages_settings
from app.sep.middleware.messages.models import Message, MessageLevel

logger = logging.getLogger("app.sep.middleware.messages")


def add_message(
    request: Request,
    level: MessageLevel,
    text: str,
    path_pattern: str | None = None,
    *,
    sticky: bool = False,
) -> None:
    """Add a message to the current request's message queue.

    This function creates a new Message object with the provided level, text, and
    sticky flag and appends it to the `messages` list in the request state. If the
    request state does not support messages, an exception is logged. Messages with a
    level lower than the configured minimum level in `messages_settings` are ignored.

    :param request: The HTTP request object.
    :type request: Request
    :param level: The level of the message.
    :type level: MessageLevel
    :param text: The text content of the message.
    :type text: str
    :param path_pattern: An optional path regex pattern associated with the message.
        If provided, the message will only be shown on requests matching this pattern.
    :type path_pattern: str | None
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    :raises AttributeError: If the request does not have a messages attribute.
    :raises ValueError: If the message data is invalid and fails validation.
    """
    if level >= messages_settings.LEVEL:
        try:
            message = Message(
                level=level, text=text, path_pattern=path_pattern, sticky=sticky
            )
            request.state.messages[message] = None
        except AttributeError:
            logger.exception("Unable to add messages without MessageMiddleware")
        except ValueError:
            logger.exception("Error building Message object")
        else:
            logger.debug("Sending message to %s: %s", request.client.host, message)
    else:
        logger.debug(
            "Ignoring message below configured level %s: %s",
            messages_settings.LEVEL,
            level,
        )


def get_messages(request: Request, max_qty: int | None = None) -> list[Message]:
    """Retrieve and remove messages from the request state.

    This function fetches messages stored in the request state (up to `max_qty` if
    specified), removes them from the state, and returns them as a list. Messages with
    non-nullable path patterns that doesn't match the current requested path are
    retained in the state for future retrieval.

    :param request: The HTTP request object.
    :type request: Request
    :param max_qty: Optional maximum number of messages to retrieve. If None (default),
        all messages are returned.
    :type max_qty: int | None
    :return: A list of Message objects.
    :rtype: list[Message]
    """
    messages = []
    messages_to_save = []
    saved_messages = getattr(request.state, "messages", None)
    current_path = request.scope.get("path_pattern") or request.url.path
    logger.debug("Retrieving messages for %s: %s", current_path, saved_messages)
    while saved_messages and (max_qty is None or len(messages) < max_qty):
        message, _ = saved_messages.popitem(last=False)
        if message.path_pattern is None or message.path_pattern.match(current_path):
            messages.append(message)
        else:
            messages_to_save.append(message)
    logger.debug("Retrieved messages for %s: %s", current_path, messages)
    logger.debug("Saving messages for %s: %s", current_path, messages_to_save)
    request.state.messages = OrderedDict.fromkeys(
        messages_to_save + list(saved_messages or [])
    )
    return messages


def info(
    request: Request,
    text: str,
    path_pattern: str | None = None,
    *,
    sticky: bool = False,
) -> None:
    """Add an informational message to the request's message queue.

    This is a convenience function that adds a message with the INFO level.

    :param request: The HTTP request object.
    :type request: Request
    :param text: The informational message text.
    :type text: str
    :param path_pattern: An optional path regex pattern associated with the message.
        If provided, the message will only be shown on requests matching this pattern.
    :type path_pattern: str | None
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    """
    add_message(request, MessageLevel.INFO, text, path_pattern, sticky=sticky)


def success(
    request: Request,
    text: str,
    path_pattern: str | None = None,
    *,
    sticky: bool = False,
) -> None:
    """Add a success message to the request's message queue.

    This is a convenience function that adds a message with the SUCCESS level.

    :param request: The HTTP request object.
    :type request: Request
    :param text: The success message text.
    :type text: str
    :param path_pattern: An optional path regex pattern associated with the message.
        If provided, the message will only be shown on requests matching this pattern.
    :type path_pattern: str | None
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    """
    add_message(request, MessageLevel.SUCCESS, text, path_pattern, sticky=sticky)


def warning(
    request: Request,
    text: str,
    path_pattern: str | None = None,
    *,
    sticky: bool = False,
) -> None:
    """Add a warning message to the request's message queue.

    This is a convenience function that adds a message with the WARNING level.

    :param request: The HTTP request object.
    :type request: Request
    :param text: The warning message text.
    :type text: str
    :param path_pattern: An optional path regex pattern associated with the message.
        If provided, the message will only be shown on requests matching this pattern.
    :type path_pattern: str | None
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    """
    add_message(request, MessageLevel.WARNING, text, path_pattern, sticky=sticky)


def error(
    request: Request,
    text: str,
    path_pattern: str | None = None,
    *,
    sticky: bool = False,
) -> None:
    """Add an error message to the request's message queue.

    This is a convenience function that adds a message with the ERROR level.

    :param request: The HTTP request object.
    :type request: Request
    :param text: The error message text.
    :type text: str
    :param path_pattern: An optional path regex pattern associated with the message.
        If provided, the message will only be shown on requests matching this pattern.
    :type path_pattern: str | None
    :param sticky: Whether the message should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    """
    add_message(request, MessageLevel.ERROR, text, path_pattern, sticky=sticky)


def from_validation_error(
    request: Request,
    exc: ValidationError,
    base_text: str = "Error",
    path_pattern: str | None = None,
    *,
    sticky: bool = False,
    exclude_types: Iterable[str] = (),
) -> None:
    """Add error messages to the request from a Pydantic ValidationError.

    This function iterates over the errors in the provided ValidationError and adds
    error messages to the request's message queue. It allows for customization of the
    base text of the message, an optional path pattern, and the ability to exclude
    certain error types.

    :param request: The HTTP request object.
    :type request: Request
    :param exc: The Pydantic ValidationError instance.
    :type exc: ValidationError
    :param base_text: The base text for the error messages, defaults to "Error".
    :type base_text: str
    :param path_pattern: An optional path regex pattern associated with the messages.
        If provided, the messages will only be shown on requests matching this pattern.
    :type path_pattern: str | None
    :param sticky: Whether the messages should persist until explicitly dismissed,
        defaults to False.
    :type sticky: bool
    :param exclude_types: An iterable of error types to exclude from messaging.
        Defaults to an empty tuple.
    :type exclude_types: Iterable[str]
    """
    for err in exc.errors():
        if err.get("type") not in exclude_types:
            err_msg = base_text
            if err_loc := err.get("loc", ()):
                err_msg += f" [{loc_to_dot_sep(err_loc)}]"
            if err_msg_detail := err.get("msg"):
                err_msg += f": {err_msg_detail}"
            error(request, err_msg, path_pattern, sticky=sticky)
