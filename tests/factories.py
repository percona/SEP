"""Define reusable model factories for tests."""

from polyfactory.factories.pydantic_factory import ModelFactory

from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor import CasdoorSDK


class CasdoorSDKFactory(ModelFactory[CasdoorSDK]):
    """Define factory for CasdoorSDK instances."""


class OAuthTokenFactory(ModelFactory[OAuthToken]):
    """Define factory for OAuthToken instances."""
