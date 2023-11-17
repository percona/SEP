"""
SEP authentication and authorization library
"""
from http import HTTPStatus
from typing import (
    Awaitable,
    Optional,
)

from tornado.log import app_log
from tornado.web import HTTPError

from ..core import BaseHandler

__all__ = ["AuthZHandler"]


class AuthZHandler(BaseHandler):
    """Authorization handler"""

    def data_received(self, chunk: bytes) -> Optional[Awaitable[None]]:
        pass

    async def _signin(self) -> None:
        """Process signin requests

        :raises HTTPError: when the code does not meet expectations
        """
        if self.get_argument(name="code", default="") in [None, "", False]:
            raise HTTPError(status_code=HTTPStatus.NOT_FOUND)
        user = await self.get_authenticated_user(code=self.get_argument("code"))
        if user.get("isForbidden", True) is False:
            session = self.get_current_session()
            session.update(user=user["id"])
            self.generate_session(data=session)
            app_log.debug("Target: %s", session.get("next"))
            self.redirect(session.get("next", "/"))
            return

    async def _signout(self) -> None:
        """Process signout requests

        Clear the Casdoor and session cookies
        """
        self.clear_cookie(self.cfg.authz.CASDOOR_COOKIE)
        self.clear_cookie(self.cfg.authz.SESSION_COOKIE)
        self.redirect("/")

    async def get(self, route: str | bytes) -> None:
        """Handle GET authz requests

        :param route: the route fragment from the handler
        :type route: str, bytes
        """
        await getattr(self, f"_{route}")()
