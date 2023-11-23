"""
Tasks module
"""
import json
from os.path import join

from tornado.httpclient import (
    AsyncHTTPClient,
    HTTPRequest,
)
from tornado.log import app_log

from ..core import ApiBackendHandler
from ..core.utils import (
    get_template,
    render_template,
)

TEMPLATE_PREFIX = "tasks"


class DefaultHandler(ApiBackendHandler):
    """Default handler for Tasks UI"""

    uri: str = "api/"

    async def _list(self) -> list:
        """

        :return:
        """
        client = AsyncHTTPClient()
        response = await client.fetch(
            HTTPRequest(
                url=f"{self.request.server_connection.context.protocol}://{self.request.host}{self.request.uri}{self.uri}",
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
        app_log.debug("Received request to tasks handler: %r", self.request)
        match route:
            case _:
                render_args = {
                    "data": await self._list()
                }
                template_name = join(TEMPLATE_PREFIX, "list.html")
        self.write(render_template(get_template(template_name, self.cfg.templates.get("dirs", [])), **render_args))
