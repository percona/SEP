"""
SEP core functionality

The sep.core module primarily provides reusable resources for other modules,
such as a base request handler, dummy handler, etc
"""

from collections import namedtuple
from http import HTTPStatus
import json
from os import getenv
from typing import (
    Any,
    Awaitable,
    Dict,
    Optional,
    Union,
)

from tornado.httpclient import (
    AsyncHTTPClient,
    HTTPRequest,
)
from tornado.log import app_log
from tornado.web import (
    authenticated,
    HTTPError,
    RequestHandler,
)

from ..authz.casdoor import CasdoorOAuth2Mixin

__all__ = ["DummyHandler", "RemoteCallHandler"]


class BaseHandler(RequestHandler, CasdoorOAuth2Mixin):
    """
    Base request handler
    """

    cfg: namedtuple

    def initialize(self) -> None:
        self.cfg = self.application.config

    def data_received(self, chunk: bytes) -> Optional[Awaitable[None]]:
        pass

    def prepare(self):
        super().prepare()
        session = self.get_current_session()
        if not session:
            self.generate_session()
            self.redirect(self.request.uri)
            return
        app_log.debug("Session: %r", session)

        if getenv("SEP_FORCE_NO_AUTH", "0") == "1":
            return

        @authenticated
        def _prepare(obj):
            user = obj.get_current_user()
            if "user" not in session:
                session["user"] = user["id"]
                obj.generate_session(data=session)
                obj.redirect(obj.request.uri)
                return
            if session["user"] != user["id"]:
                raise HTTPError(status_code=HTTPStatus.FORBIDDEN)

        if self.__class__.__name__ != "AuthZHandler":
            _prepare(self)

    def get_current_user(self) -> Union[Dict[str, Any], None]:
        """Retrieve the current user

        :return: the current user information
        :rtype: dict | None
        """
        user_cookie = self.get_signed_cookie(self.cfg.authz.CASDOOR_COOKIE)
        if user_cookie:
            return json.loads(user_cookie)
        return None

    def get_current_session(self) -> Union[Dict[str, Any], None]:
        """Retrieve the current session

        :return: the current session data
        :rtype: dict | None
        """
        session_cookie = self.get_signed_cookie(self.cfg.authz.SESSION_COOKIE)
        if session_cookie:
            return json.loads(session_cookie)
        return None

    def get_login_url(self) -> str:
        """Retrieve the login url

        :return: the login url for Casdoor
        :rtype: str
        """
        return self.cfg.authz.CASDOOR_SDK_SYNC.get_auth_link(redirect_uri=self.cfg.authz.REDIRECT_URI)


class DummyHandler(BaseHandler):
    """
    Dummy handler use for all unrouted requests
    """

    async def get(self) -> None:
        """Server GET requests"""
        app_log.debug("Received request to dummy handler: %r", self.request)
        msg = "Nothing to see here, move along"
        if "json" in self.request.headers.get("content-type", "") or "json" in self.request.headers.get("accept", ""):
            self.set_header("content-type", "application/json; charset=UTF-8")
            msg = json.dumps({"message": msg})
        self.write(msg)


class RemoteCallHandler(BaseHandler):
    """
    Handler to proxy requests to remote services
    """

    uri = None

    connect_timeout: int
    follow_redirects: bool
    request_timeout: int

    def initialize(self, **kwargs) -> None:
        """Hook for local config loading"""
        super().initialize()
        self.uri = kwargs["uri"]

        self.connect_timeout = kwargs.get("connect_timeout", 10)
        self.follow_redirects = kwargs.get("follow_redirects", True)
        self.request_timeout = kwargs.get("request_timeout", 60)

    async def get(self, **kwargs) -> None:
        """Server GET requests

        :param kwargs: parameters taken from routing
        """
        client = AsyncHTTPClient()
        response = await client.fetch(
            HTTPRequest(
                url=f"{self.uri}/{kwargs.get('route', '')}",
                method="GET",
                headers=self._headers,
                connect_timeout=self.connect_timeout,
                follow_redirects=self.follow_redirects,
                request_timeout=self.request_timeout,
            )
        )
        self.set_header("content-type", response.headers.get("content-type"))
        self.write(response.body)

    async def post(self, **kwargs) -> None:
        """Server POST requests

        :param kwargs: parameters taken from routing
        """
        client = AsyncHTTPClient()
        response = await client.fetch(
            HTTPRequest(
                url=f"{self.uri}/{kwargs.get('route', '')}",
                method="POST",
                headers=self._headers,
                connect_timeout=self.connect_timeout,
                follow_redirects=self.follow_redirects,
                request_timeout=self.request_timeout,
            )
        )
        self.set_header("content-type", response.headers.get("content-type"))
        self.write(response.body)
