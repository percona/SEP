"""Define reusable exceptions."""

from app.core.auth.exceptions import HTTPTemporaryRedirectException
from app.sep.config import sep_settings

OAuthRedirectException = HTTPTemporaryRedirectException(sep_settings.OAUTH.AUTH_LINK)
