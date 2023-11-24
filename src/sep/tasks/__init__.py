"""
Tasks module
"""
from base64 import b64encode
from collections import namedtuple
from http import HTTPStatus
import json
from os.path import join
from urllib.parse import parse_qs

from tornado.httpclient import (
    AsyncHTTPClient,
    HTTPRequest,
)
from tornado.log import app_log
from tornado.web import HTTPError
import yaml

from .api.models import TASK_BACKEND_MAP
from ..core import ApiBackendHandler
from ..core.utils import (
    get_template,
    JSONEncoder,
    render_template,
)

TranslateConfig = namedtuple("TranslateConfig", ["old", "new", "action"])

TEMPLATE_PREFIX = "tasks"
TRANSLATION_MAPPING = {
    "create": (
        TranslateConfig("taskalias", "name", "flatten"),
        TranslateConfig("taskdef", "data", "base64"),
        TranslateConfig("taskeng", "engine", "flatten"),
    )
}


class DefaultHandler(ApiBackendHandler):
    """Default handler for Tasks UI"""

    uri: str

    def initialize(self) -> None:
        """
        Perform setup tasks

        :return:
        """
        super().initialize()
        self.uri = f"{self.request.server_connection.context.protocol}://{self.request.host}{self.request.uri}api/"

    async def _create(self) -> list:
        """

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
                case "base64":
                    # TODO: add validation for the format
                    if payload.get("format") == ["yaml"]:
                        payload[mapping.old][0] = json.dumps(yaml.safe_load(payload[mapping.old][0]))
                    payload[mapping.new] = b64encode(payload[mapping.old][0].encode()).decode()
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
        """

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

    async def get(self, route: str):
        """Task UI requests

        :param route: the parameters sent in from the router
        :type route: str
        :return:
        """
        app_log.debug("Received GET request to tasks handler: %r", self.request)
        match route:
            case _:
                render_args = {
                    "data": await self._list(),
                    "backends": dict(map(reversed, TASK_BACKEND_MAP.items())),
                    "xsrf_form_html": self.xsrf_form_html,
                }
                template_name = join(TEMPLATE_PREFIX, "list.html")
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
