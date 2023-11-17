"""
Casdoor authentication and authorization
"""
from collections import namedtuple
from http import HTTPStatus
import json
from secrets import token_hex
from typing import (
    Any,
    Dict,
    Optional,
    cast,
)

from jwt.exceptions import DecodeError
from tornado.auth import OAuth2Mixin
from tornado.log import app_log
from tornado.web import (
    HTTPError,
    RequestHandler,
)

__all__ = ["AuthzConfig", "CasdoorOAuth2Mixin"]

AuthzConfig = namedtuple(
    "AuthzConfig", ["CASDOOR_COOKIE", "CASDOOR_SDK", "CASDOOR_SDK_SYNC", "REDIRECT_URI", "SECRET_KEY", "SESSION_COOKIE"]
)


class CasdoorOAuth2Mixin(OAuth2Mixin):
    """Casdoor authentication using OAuth2"""

    # The following are not used, unlike other OAuth2Mixin classes:
    # _OAUTH_AUTHORIZE_URL
    # _OAUTH_ACCESS_TOKEN_URL
    # _OAUTH_USERINFO_URL
    # _OAUTH_NO_CALLBACKS
    # _OAUTH_SETTINGS_KEY

    cfg: namedtuple

    def get_casdoor_oauth_settings(self) -> AuthzConfig:
        """Get the Casdoor OAuth 2.0 credentials

        This is a mixin and so the configuration is set by the handler that uses
        CasdoorOAuth2Mixin.

        :raises LookupError: when "authz" is not present in self.cfg
        :returns a readonly copy of the OAuth2 settings
        :rtype AuthzConfig
        """
        if not hasattr(self.cfg, "authz"):
            raise LookupError("authz is not present in the configuration")
        return self.cfg.authz

    async def get_authenticated_user(self, code: str) -> Dict[str, Any]:
        """Handle login with Casdoor

        :param code: the code sent via the callback request from Casdoor
        :type code: str
        :raises HTTPError: when the user authentication fails
        :returns the user's details
        :rtype dict
        """
        app_log.debug("Checking authenticated user")
        handler = cast(RequestHandler, self)
        token = await self.cfg.authz.CASDOOR_SDK.get_oauth_token(code)

        try:
            user = self.cfg.authz.CASDOOR_SDK.parse_jwt_token(token.get("access_token"))
        except DecodeError as err:
            raise HTTPError(status_code=HTTPStatus.UNAUTHORIZED) from err
        # TODO: limit duration
        handler.set_signed_cookie(
            name=self.cfg.authz.CASDOOR_COOKIE,
            httponly=True,
            expires_days=None,
            samesite="lax",
            secure=self.cfg.authz.REDIRECT_URI.startswith("https://"),
            value=json.dumps(user),
        )
        return user

    def generate_session(self, data: Optional[Dict] = None):
        """Generate a session, with optional data"""
        handler = cast(RequestHandler, self)
        cookie_data = {"id": token_hex(41), "next": handler.request.uri}
        if isinstance(data, dict):
            cookie_data.update({k: v for k, v in data.items() if k not in ["id"]})
        handler.set_signed_cookie(
            name=self.cfg.authz.SESSION_COOKIE,
            httponly=True,
            expires_days=None,
            samesite="lax",
            secure=self.cfg.authz.REDIRECT_URI.startswith("https://"),
            value=json.dumps(cookie_data),
        )
