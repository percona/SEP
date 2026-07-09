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

"""Define tests for the MessagesMiddleware and related utilities."""

import json
from base64 import b64decode
from collections import OrderedDict
from unittest.mock import ANY, Mock

import pytest
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.security import crypto_serializer
from app.core.utils import b64encode_str, json_serializer
from app.sep.middleware.messages import (
    add_message,
    error,
    get_messages,
    info,
    MessagesMiddleware,
    success,
    warning,
)
from app.sep.middleware.messages.models import Message, MessageLevel


@pytest.fixture
def app_with_middleware() -> FastAPI:
    """Create an app with the MessagesMiddleware installed."""
    app = FastAPI()

    @app.get("/no-message")
    async def no_message():
        """Return a response without modifying messages."""
        return JSONResponse({"detail": "No message"})

    @app.get("/add-message")
    async def add_message_endpoint(request: Request):
        """Add a message to the request state and return a response."""
        add_message(request, MessageLevel.INFO, "hello")
        return JSONResponse({"detail": "Message added"})

    app.add_middleware(MessagesMiddleware)
    return app


@pytest.fixture
def test_client(app_with_middleware) -> TestClient:
    """Provide a TestClient for a test app with the MessagesMiddleware installed."""
    return TestClient(app_with_middleware)


@pytest.fixture
def utils_logger_mock(mocker) -> Mock:
    """Mock the logger for the app.sep.middleware.messages module."""
    return mocker.patch("app.sep.middleware.messages._utils.logger")


class TestMessage:
    """Test the Message model behavior."""

    def test_message_serialization_without_sticky(self):
        """Assert correct serialization without sticky."""
        msg = Message(level=MessageLevel.INFO, text="Test", sticky=False)
        data = msg.model_dump(by_alias=True)
        assert data["l"] == MessageLevel.INFO
        assert data["t"] == "Test"
        assert "sticky" not in data

    def test_message_serialization_with_sticky(self):
        """Assert correct serialization with sticky."""
        msg = Message(level=MessageLevel.SUCCESS, text="Test", sticky=True)
        data = msg.model_dump(by_alias=True)
        assert data["l"] == MessageLevel.SUCCESS + 1
        assert data["t"] == "Test"

    def test_message_validation_set_sticky_from_level(self):
        """Assert validator sets sticky flag based on level."""
        data = {"l": 2, "t": "Test"}
        msg = Message.model_validate(data)
        assert msg.level == MessageLevel.INFO
        assert msg.sticky is True

    def test_message_text_max_length(self):
        """Assert error is raised for text exceeding max length."""
        long_text = "a" * 513
        with pytest.raises(
            ValueError, match="String should have at most 512 characters"
        ):
            Message(level=MessageLevel.INFO, text=long_text)


class TestMessageFunctions:
    """Test add_message, get_messages, and convenience functions."""

    def test_add_message(self, dummy_request):
        """Assert add_message appends a message to the state."""
        add_message(dummy_request, MessageLevel.WARNING, "Warning message", sticky=True)
        msgs = dummy_request.state.messages
        assert len(msgs) == 1
        msg = next(iter(msgs))
        assert msg.level == MessageLevel.WARNING
        assert msg.text == "Warning message"
        assert msg.sticky is True

    @pytest.mark.parametrize(
        ("func", "expected_level"),
        [
            (info, MessageLevel.INFO),
            (success, MessageLevel.SUCCESS),
            (warning, MessageLevel.WARNING),
            (error, MessageLevel.ERROR),
        ],
    )
    def test_convenience_functions(self, dummy_request, func, expected_level):
        """Assert convenience functions add the correct message."""
        func(dummy_request, "Convenience test", sticky=False)
        msgs = dummy_request.state.messages
        assert len(msgs) == 1
        msg = next(iter(msgs))
        assert msg.level == expected_level
        assert msg.text == "Convenience test"

    def test_get_messages_all(self, dummy_request):
        """Assert get_messages returns and clears all messages."""
        msgs = [
            Message(level=MessageLevel.INFO, text="Msg 1"),
            Message(level=MessageLevel.SUCCESS, text="Msg 2"),
        ]
        dummy_request.state.messages.update(OrderedDict.fromkeys(msgs))
        ret = get_messages(dummy_request)
        assert ret == msgs
        assert dummy_request.state.messages == OrderedDict()

    def test_get_messages_partial(self, dummy_request):
        """Assert get_messages returns partial messages."""
        msgs = [
            Message(level=MessageLevel.INFO, text="Msg 1"),
            Message(level=MessageLevel.SUCCESS, text="Msg 2"),
            Message(level=MessageLevel.WARNING, text="Msg 3"),
        ]
        dummy_request.state.messages.update(OrderedDict.fromkeys(msgs))
        ret = get_messages(dummy_request, max_qty=2)
        assert ret == msgs[:2]
        assert dummy_request.state.messages == OrderedDict.fromkeys(msgs[2:])

    def test_add_message_no_state(self, utils_logger_mock):
        """Assert add_message logs an error when state lacks messages."""
        scope = {"type": "http", "headers": []}
        req = Request(scope)
        assert not hasattr(req.state, "messages")
        add_message(req, MessageLevel.INFO, "Test")
        utils_logger_mock.exception.assert_called_with(
            "Unable to add messages without MessageMiddleware"
        )

    def test_add_message_invalid(self, dummy_request, utils_logger_mock):
        """Assert add_message logs an error when Message validation fails."""
        add_message(dummy_request, MessageLevel.INFO, "a" * 513)
        utils_logger_mock.exception.assert_called_with("Error building Message object")

    def test_add_duplicate_message(self, dummy_request):
        """Assert add_message does not duplicate messages."""
        add_message(dummy_request, MessageLevel.INFO, "Duplicate test")
        add_message(dummy_request, MessageLevel.INFO, "Duplicate test")
        msgs = dummy_request.state.messages
        assert len(msgs) == 1
        msg = next(iter(msgs))
        assert msg.text == "Duplicate test"
        assert msg.level == MessageLevel.INFO


class TestMessagesMiddleware:
    """Test the MessagesMiddleware integration with FastAPI."""

    def test_middleware_loads_cookie(self, test_client):
        """Assert middleware loads messages from the cookie."""
        messages = [{"l": 1, "t": "hello"}]
        test_client.cookies["messages"] = crypto_serializer.dumps(json.dumps(messages))
        response = test_client.get("/no-message")
        assert "messages" in response.cookies
        new_value = response.cookies.get("messages")
        parsed = json.loads(crypto_serializer.loads(new_value))
        assert parsed == messages

    def test_middleware_sets_cookie(self, test_client):
        """Assert middleware sets the cookie when messages exist."""
        response = test_client.get("/add-message")
        assert "messages" in response.cookies
        new_value = response.cookies.get("messages")
        parsed = json.loads(crypto_serializer.loads(new_value))
        assert len(parsed) == 1
        msg = parsed[0]
        assert msg["t"] == "hello"
        assert msg["l"] == 1

    def test_middleware_deletes_cookie(self, test_client):
        """Assert middleware deletes the cookie when no messages exist."""
        response = test_client.get("/no-message")
        set_cookie = response.headers.get("set-cookie", "")
        assert 'messages="";' in set_cookie

    def test_middleware_cookie_size_limit(
        self, app_with_middleware, test_client, monkeypatch, mocker
    ):
        """Assert middleware pops messages to satisfy the cookie size limit."""
        default_max_cookie_size = MessagesMiddleware.MAX_COOKIE_SIZE
        with monkeypatch.context() as context:
            context.setattr(
                "app.sep.middleware.messages._middleware.crypto_serializer.dumps",
                b64encode_str,
            )
            logger_mock = mocker.patch("app.sep.middleware.messages._middleware.logger")

            @app_with_middleware.get("/add-two-messages")
            async def add_two_messages(request: Request):
                """Add two messages to the request state."""
                add_message(request, MessageLevel.INFO, "A")
                add_message(request, MessageLevel.INFO, "B")
                return JSONResponse({"detail": "Two messages added"})

            one_msg = Message(level=MessageLevel.INFO, text="A")
            one_msg_cookie = b64encode_str(
                json_serializer(
                    [one_msg.model_dump(by_alias=True)], separators=(",", ":")
                )
            )
            context.setattr(
                MessagesMiddleware, "MAX_COOKIE_SIZE", len(one_msg_cookie) + 5
            )

            response = test_client.get("/add-two-messages")
            new_value = response.cookies.get("messages")
            parsed = json.loads(b64decode(new_value))
            assert len(parsed) == 1

            logger_mock.debug.assert_called_with(
                "Discarding message %s for %s", ANY, ANY
            )

        assert default_max_cookie_size == MessagesMiddleware.MAX_COOKIE_SIZE

    @pytest.mark.parametrize(
        "bad_cookie",
        [
            "totally-invalid-signature",
            "not-even-base64!@#$",
            crypto_serializer.dumps(json.dumps([{"l": 1}])),
        ],
        ids=["bad_signature", "garbage", "validation_error"],
    )
    def test_middleware_clears_invalid_cookie(self, test_client, bad_cookie):
        """Assert an invalid messages cookie yields a normal response with the cookie cleared."""
        test_client.cookies["messages"] = bad_cookie
        response = test_client.get("/no-message")
        assert response.status_code == status.HTTP_200_OK
        set_cookie = response.headers.get("set-cookie", "")
        assert 'messages="";' in set_cookie
