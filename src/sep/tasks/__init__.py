"""
Tasks module
"""
from base64 import b64encode
from collections import namedtuple
from http import HTTPStatus
import json
from os.path import join
from typing import Any, Optional
from urllib.parse import parse_qs

import requests
import uvloop
from nomad import Nomad
from tornado import httputil
from tornado.httpclient import (
    AsyncHTTPClient,
    HTTPClientError,
    HTTPRequest,
)
from tornado.log import app_log
from tornado.web import HTTPError
import yaml

from .api.models import TASK_BACKEND_LOOKUP
from ..core import ApiBackendHandler
from ..core.utils import (
    async_run,
    get_template,
    render_template,
)

TranslateConfig = namedtuple("TranslateConfig", ["old", "new", "action"])

DEFAULT_BACKEND_ADDRESS = "http://127.0.0.1:8182"

TEMPLATE_PREFIX = "tasks"
TRANSLATION_MAPPING = {
    "create": (
        TranslateConfig("taskalias", "name", "flatten"),
        TranslateConfig("taskdef", "data", "json"),
        TranslateConfig("taskeng", "engine", "flatten"),
    )
}


class TaskHandler(ApiBackendHandler):
    """Default handler for Tasks UI"""

    PATHS = {
        "api": "/tasks/api/",
        "ui": "/tasks/",
    }

    uri: str

    def initialize(self) -> None:
        """
        Perform setup tasks

        :return:
        """
        super().initialize()
        self.uri = f"{self.request.server_connection.context.protocol}://{self.request.host}{TaskHandler.PATHS['api']}"

    async def _create(self) -> dict:
        """Create a new task

        :return:
        """
        client = AsyncHTTPClient()
        headers = dict(self.request.headers.copy())
        headers["Content-Type"] = "application/json"
        payload = parse_qs(self.request.body.decode())

        if "_xsrf" in payload:
            headers["X-Xsrftoken"] = payload["_xsrf"][0]
            del payload["_xsrf"]
        for mapping in TRANSLATION_MAPPING["create"]:
            if mapping.old not in payload:
                continue
            match mapping.action:
                case "json":
                    # TODO: add validation for the format
                    if payload.get("format") == ["yaml"]:
                        payload[mapping.new] = json.dumps(yaml.safe_load(payload[mapping.old][0]))
                    elif payload.get("format") == ["hcl"]:
                        session = requests.Session()

                        for c, v in self.cookies.items():
                            if c not in ["_xsrf", "fastapi-session", "casdoorUser", "sep"]:
                                continue
                            if c == "_xsrf":
                                session.headers.setdefault("X-Xsrftoken", v.value)
                            session.cookies.set(c, v.value)

                        parsed = await async_run(
                            Nomad(**self.cfg.modules.nomad.backend, session=session).jobs.parse,
                            payload[mapping.old][0]
                        )
                        payload[mapping.new] = json.dumps(parsed)
                    else:
                        payload[mapping.new] = payload[mapping.old][0]
                case "flatten":
                    if not isinstance(payload[mapping.old], list):
                        payload[mapping.new] = payload[mapping.old]
                    else:
                        payload[mapping.new] = payload[mapping.old][0]
                case _:
                    payload[mapping.new] = payload[mapping.old]
            del payload[mapping.old]

        response = await client.fetch(
            HTTPRequest(
                url=self.uri,
                method="POST",
                body=json.dumps(payload),
                headers=headers,
                connect_timeout=self.connect_timeout,
                follow_redirects=self.follow_redirects,
                request_timeout=self.request_timeout,
            )
        )
        return json.loads(response.body.decode())

    async def _list(self) -> list:
        """Lookup all tasks

        :return:
        """
        client = AsyncHTTPClient()
        response = await client.fetch(
            HTTPRequest(
                url=self.uri,
                method="GET",
                headers=self.request.headers,
                connect_timeout=self.connect_timeout,
                follow_redirects=self.follow_redirects,
                request_timeout=self.request_timeout,
            )
        )
        return json.loads(response.body.decode())

    async def _view(self, task: str) -> dict:
        """View a specific task

        :param task:
        :return:
        """
        client = AsyncHTTPClient()
        response = await client.fetch(
            HTTPRequest(
                url=f"{self.uri}{task}",
                method="GET",
                headers=self.request.headers,
                connect_timeout=self.connect_timeout,
                follow_redirects=self.follow_redirects,
                request_timeout=self.request_timeout,
            )
        )
        return json.loads(response.body.decode())

    async def get(self, route: str):
        """Task UI requests

        :param route: the parameters sent in from the router
        :type route: str
        :return:
        """
        app_log.debug("Received GET request to tasks handler: %r", self.request)
        render_args = {
            "backends": TASK_BACKEND_LOOKUP,
            "base_uri": self.PATHS["ui"],
            "xsrf_form_html": self.xsrf_form_html,
        }
        match route:
            case "":
                render_args.update(data=await self._list())
                template_name = join(TEMPLATE_PREFIX, "list.html")
            case _:
                try:
                    render_args.update(data=await self._view(route))
                except HTTPClientError as err:
                    raise HTTPError(status_code=HTTPStatus.NOT_FOUND) from err
                template_name = join(TEMPLATE_PREFIX, "view.html")
        self.write(render_template(get_template(template_name, self.cfg.templates.get("dirs", [])), **render_args))

    async def post(self, route: str):
        """Task UI post requests

        :param route: the parameters sent in from the router
        :type route: str
        :return:
        """
        app_log.debug("Received POST request to tasks handler: %r", self.request)
        match route:
            case "":
                _ = await self._create()
                self.redirect(self.request.uri)
            case _:
                raise HTTPError(status_code=HTTPStatus.METHOD_NOT_ALLOWED)
