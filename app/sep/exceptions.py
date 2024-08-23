"""Define reusable exceptions."""

from app.core.auth.exceptions import HTTPTemporaryRedirectException
from app.core.config import settings

OAuthRedirectException = HTTPTemporaryRedirectException(settings.AUTH.OAUTH_LINK)
