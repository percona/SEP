"""
SEP core functionality

The sep.core module primarily provides reusable resources for other modules,
such as a base request handler, dummy handler, etc
"""

from collections import namedtuple
from http import HTTPStatus
import json
from os import getenv
from re import sub
from time import time_ns
import traceback
from typing import (
    Any,
    Awaitable,
    Dict,
    Optional,
    Union,
)
from urllib.parse import (
    parse_qs,
    urlparse,
)

from tornado.gen import coroutine
from tornado.httpclient import (
    AsyncHTTPClient,
    HTTPClientError,
    HTTPRequest,
)
from tornado.log import app_log
from tornado.web import (
    authenticated,
    HTTPError,
    RequestHandler,
)

from ..authz.casdoor import CasdoorOAuth2Mixin
from ..core.utils import async_request
from .utils import (
    get_template,
    render_template,
)

__all__ = ["ApiBackendHandler", "DummyHandler", "HomepageHandler", "RemoteCallHandler"]


class BaseHandler(RequestHandler, CasdoorOAuth2Mixin):
    """
    Base request handler
    """
    TEMPLATE_PATH = None

    cfg: namedtuple
    data: dict = {
        "user": None,
        "casdoor_login_url": None,
        "template_data": {},
        "template_path": "dummy.html",
        "xsrf_form_html": "",
    }

    def initialize(self) -> None:
        self.cfg = getattr(self.application, "config")

        needs_json = False
        for header in ["accept", "content-type"]:
            if "json" in self.request.headers.get(header, ""):
                self.set_header("Content-Type", "application/json")
                needs_json = True
                break
        self.data.update(
            xsrf_form_html=self.xsrf_form_html,
            file_extension="json" if needs_json else "html",
        )
        if self.TEMPLATE_PATH is not None:
            self.data["template_path"] = self.TEMPLATE_PATH

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

        self.data.update(
            {
                "user": self.get_current_user(),
                "casdoor_login_url": urlparse(self.get_login_url()),
            }
        )

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
            # TODO: add support for TLS
            address = self.cfg.sep.processes[self.cfg.lookups.audit]
            response = client.fetch(
                HTTPRequest(
                    url=f"http://{address['host']}:{address['port']}/",
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

    def finish(self, chunk: Optional[Union[str, bytes, dict]] = None) -> "Future[None]":
        """Automatically render the template and data

        :param chunk:
        :return:
        """
        if chunk is None:
            template = get_template(self.data["template_path"], self.cfg.templates.get("dirs", []))
            chunk = sub(
                rf'href="{self.request.uri}"', r'class="selected"', render_template(template, data=self.data).decode()
            ).encode("utf-8")
        super().finish(chunk=chunk)

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

    def write_error(self, status_code: int, **kwargs: Any) -> None:
        """Custom error pages.

        ``write_error`` may call `write`, `render`, `set_header`, etc
        to produce output as usual.

        If this error was caused by an uncaught exception (including
        HTTPError), an ``exc_info`` triple will be available as
        ``kwargs["exc_info"]``.  Note that this exception may not be
        the "current" exception for purposes of methods like
        ``sys.exc_info()`` or ``traceback.format_exc``.
        """
        trace_info = (
            traceback.format_exception(*kwargs["exc_info"])
            if self.settings.get("serve_traceback") and "exc_info" in kwargs
            else []
        )
        self.data.update(template_path=f"error.{self.data['file_extension']}")
        self.data["template_data"].update(status_code=status_code, error=kwargs, trace=trace_info)


class ApiBackendHandler(BaseHandler):
    """Default handler for UIs talking to an API"""

    connect_timeout: int = 10
    follow_redirects: bool = False
    request_timeout: int = 60

    async def post(self, route: str):
        """API Backend post requests

        :param route: the parameters sent in from the router
        :type route: str
        :return:
        """
        app_log.debug("Received POST request to API handler: %r", self.request)

        match self.request.arguments.get("location"):
            case None:
                raise HTTPError(status_code=HTTPStatus.METHOD_NOT_ALLOWED)
            case _:
                payload = parse_qs(self.request.body.decode())
                url = payload["location"][0]
                target_url = urlparse(url)
                if not target_url.scheme:
                    request_url = urlparse(self.uri)
                    url = f"{request_url.scheme}://{request_url.netloc}{url}"
                del payload["location"]
                if "_xsrf" in payload:
                    self.request.headers.add("X-XSRF-TOKEN", payload["_xsrf"][0])
                    self.request.headers.add("X-Xsrftoken", payload["_xsrf"][0])
                self.request.headers.update({"Content-type": "application/json"})
                response = await async_request(
                    url=url,
                    request=self.request,
                    method="POST",
                    payload={k: v[0] for k, v in payload.items() if k not in ["_xsrf"]},
                )
                app_log.debug("Response: %r", response)


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
        self.data.update(template_path=f"dummy.{suffix}")


class HomepageHandler(BaseHandler):
    """Landing page for the main application"""

    async def get(self) -> None:
        """Serve the homepage"""
        app_log.debug("Received request to homepage handler: %r", self.request)
        # TODO: create way to request data from apps, e.g. /widget

        widgets = self.application.config.sep.get("widgets", [])
        widget_data = []

        for widget in widgets:
            match widget:
                case "archiver" | "inventory" | "alters":
                    # TODO: named routing would help here
                    data = await async_request(
                        # Supporting only "internal" widgets
                        url=f"{self.request.protocol}://{self.request.host}/{widget}/api/widget",
                        request=self.request,
                        raise_error=False,
                    )
                    if isinstance(data, dict):
                        widget_data.append(data)
                case _:
                    app_log.warning("Widget for %s is not supported ", widget)

        self.data.update(
            template_path="homepage.html",
            template_data={"dashboard": {"widgets": widget_data}},
        )


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
        self.finish(chunk=response.body)

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
        self.finish(chunk=response.body)
