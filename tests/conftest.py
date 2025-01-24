"""Define a global test configuration."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Set environment variables for testing."""
    import os

    os.environ["CASDOOR__CLIENT_ID"] = "test-client-id"
    os.environ["CASDOOR__CLIENT_SECRET"] = "test-client-secret"
    os.environ["CASDOOR__ALLOWED_ISSUERS"] = '["https://allowed-issuer.com"]'
    os.environ["ALLOWED_HOSTS"] = '["testserver"]'
