"""
Tasks module
"""
from http import HTTPStatus
import json
from os.path import join

from tornado.httpclient import (
    AsyncHTTPClient,
    HTTPRequest,
)
from tornado.log import app_log
from tornado.web import HTTPError

from ..core import ApiBackendHandler
from ..core.utils import (
    get_template,
    render_template,
)

TEMPLATE_PREFIX = "tasks"


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
        payload = self.request.body_arguments
        response = await client.fetch(
            HTTPRequest(
                url=self.uri,
                method="POST",
                body=json.dumps(payload, ensure_ascii=False),
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