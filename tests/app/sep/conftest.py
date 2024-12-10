"""Define test fixtures for the SEP app."""

import pytest
from fastapi.testclient import TestClient

from app.models import CasdoorUser
from app.sep.deps import get_current_user, validate_csrf
from app.sep.main import sep_app


@pytest.fixture
def test_client(regular_user: CasdoorUser) -> TestClient:
    """Create an authenticated test client for the app."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    yield TestClient(sep_app)
    sep_app.dependency_overrides = {}
