"""
SEP core functionality

The sep.core module primarily provides reusable resources for other modules,
such as a base request handler, dummy handler, etc
"""

from collections import namedtuple
from http import HTTPStatus
import json
from os import getenv
from time import time_ns
from typing import (
    Any,
    Awaitable,
    Dict,
    Optional,
    Union,
)
from urllib.parse import urlparse

from tornado.gen import coroutine
from tornado.httpclient import (
    AsyncHTTPClient,
    HTTPClientError,
    HTTPRequest,
)
from tornado.log import app_log
from tornado.options import options
from tornado.web import (
    authenticated,
    HTTPError,
    RequestHandler,
)

from ..authz.casdoor import CasdoorOAuth2Mixin
from .utils import (
    get_template,
    render_template,
)

__all__ = ["ApiBackendHandler", "DummyHandler", "HomepageHandler", "RemoteCallHandler"]


class BaseHandler(RequestHandler, CasdoorOAuth2Mixin):
    """
    Base request handler
    """

    cfg: namedtuple

    def initialize(self) -> None:
        self.cfg = getattr(self.application, "config")

    def data_received(self, chunk: bytes) -> Optional[Awaitable[None]]:
        pass

    @coroutine
    def prepare(self):
        session = self.get_current_session()
        super().prepare()
        if not session:
            self.audit(timestamp=time_ns(), uri=self.request.uri, session=session)
            app_log.debug("Redirecting, user without session")
            self.generate_session()
            self.redirect(self.request.uri)
            return
        self.audit(timestamp=time_ns(), uri=self.request.uri, session=session)
        app_log.debug("Session: %r", session)

        if getenv("SEP_FORCE_NO_AUTH", "0") == "1":
            return

        @authenticated
        def _prepare(obj):
            user = obj.get_current_user()
            if "user" not in session:
                app_log.debug("Redirecting, user absent from session")
                session["user"] = user["id"]
                obj.generate_session(data=session)
                obj.redirect(obj.request.uri)
                return
            if session["user"] != user["id"]:
                raise HTTPError(status_code=HTTPStatus.FORBIDDEN)

        if self.__class__.__name__ != "AuthZHandler":
            _prepare(self)

    @coroutine
    def audit(self, **kwargs):
        """Audit"""
        client = AsyncHTTPClient()
        try:
            headers = dict(self.request.headers.copy())
            headers["Content-Type"] = "application/json"
            response = client.fetch(
                HTTPRequest(
                    url=f"http://127.0.0.1:{options.port + 2}/",
                    method="POST",
                    headers=headers,
                    body=json.dumps(kwargs),
                    connect_timeout=5,
                    follow_redirects=False,
                    request_timeout=60,
                )
            )
            yield response
        except HTTPClientError:
            app_log.critical("Failed to send audit message: %r", kwargs, exc_info=True)

    @coroutine
    def on_finish(self) -> None:
        """

        :return:
        """
        self.audit(
            timestamp=time_ns(), uri=self.request.uri, session=self.get_current_session(), status=self.get_status()
        )

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


class ApiBackendHandler(BaseHandler):
    """Default handler for UIs talking to an API"""

    connect_timeout: int = 10
    follow_redirects: bool = False
    request_timeout: int = 6


class DummyHandler(BaseHandler):
    """
    Dummy handler use for all unrouted requests
    """

    async def get(self) -> None:
        """Server GET requests"""
        app_log.debug("Received request to dummy handler: %r", self.request)
        suffix = "html"
        if "json" in self.request.headers.get("content-type", "") or "json" in self.request.headers.get("accept", ""):
            self.set_header("content-type", "application/json; charset=UTF-8")
            suffix = "json"
        self.set_status(status_code=HTTPStatus.NOT_FOUND)
        self.write(render_template(get_template(f"dummy.{suffix}", self.cfg.templates.get("dirs", []))))


class HomepageHandler(BaseHandler):
    """Landing page for the main application"""

    async def get(self) -> None:
        """Serve the homepage"""
        app_log.debug("Received request to homepage handler: %r", self.request)
        data = {
            "user": self.get_current_user(),
            "casdoor_login_url": urlparse(self.get_login_url()),
        }
        self.write(render_template(get_template("homepage.html", self.cfg.templates.get("dirs", [])), data=data))


class RemoteCallHandler(BaseHandler):
    """
    Handler to proxy requests to remote services
    """

    request_options: dict = {}
    uri: str | None = None

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
                headers=self.request.headers,
                connect_timeout=self.connect_timeout,
                follow_redirects=self.follow_redirects,
                request_timeout=self.request_timeout,
                **self.request_options,
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
                body=self.request.body,
                headers=self.request.headers,
                connect_timeout=self.connect_timeout,
                follow_redirects=self.follow_redirects,
                request_timeout=self.request_timeout,
                **self.request_options,
            )
        )
        self.set_header("content-type", response.headers.get("content-type"))
        self.write(response.body)
