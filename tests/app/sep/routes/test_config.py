# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define tests for the ``app.sep.routes.config`` module."""

from datetime import datetime, UTC

import pytest
import yaml
from fastapi.testclient import TestClient
from starlette.status import HTTP_200_OK, HTTP_303_SEE_OTHER

from app.models import CasdoorUser
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    validate_csrf,
)
from app.sep.main import sep_app
from app.sep.routes.config import (
    _redact_string,
    collect_effective_config,
    redact,
    REDACTED_PLACEHOLDER,
    SENSITIVE_KEY_PATTERNS,
)


@pytest.fixture
def admin_test_client(admin_user: CasdoorUser) -> TestClient:
    """Return a test client authenticated as an admin user."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


class TestRedactHelper:
    """Unit tests for :func:`redact` and its helpers."""

    def test_redacts_sensitive_keys(self):
        """Redact dict values whose key matches a sensitive pattern."""
        data = {
            "SECRET_KEY": "topsecret",
            "PASSWORD": "hunter2",
            "API_KEY": "abc123",
            "TOKEN": "xyz789",
            "UVICORN_HOST": "127.0.0.1",
        }
        result = redact(data)
        assert result["SECRET_KEY"] == REDACTED_PLACEHOLDER
        assert result["PASSWORD"] == REDACTED_PLACEHOLDER
        assert result["API_KEY"] == REDACTED_PLACEHOLDER
        assert result["TOKEN"] == REDACTED_PLACEHOLDER
        assert result["UVICORN_HOST"] == "127.0.0.1"

    def test_redaction_is_case_insensitive(self):
        """Match key-name patterns regardless of key casing."""
        result = redact({"Client_Secret": "v", "client_password": "v"})
        assert result["Client_Secret"] == REDACTED_PLACEHOLDER
        assert result["client_password"] == REDACTED_PLACEHOLDER

    def test_redacts_nested_structures(self):
        """Recurse into nested dicts and lists."""
        data = {
            "TASKS": {
                "DATABASE": {"PASSWORD": "leaky", "USER": "admin"},
                "ITEMS": [{"api_key": "hidden"}, {"name": "visible"}],
            },
        }
        result = redact(data)
        assert result["TASKS"]["DATABASE"]["PASSWORD"] == REDACTED_PLACEHOLDER
        assert result["TASKS"]["DATABASE"]["USER"] == "admin"
        assert result["TASKS"]["ITEMS"][0]["api_key"] == REDACTED_PLACEHOLDER
        assert result["TASKS"]["ITEMS"][1]["name"] == "visible"

    def test_preserves_null_on_sensitive_keys(self):
        """Leave ``None`` values untouched so empty configs stay empty."""
        result = redact({"PASSWORD": None, "API_KEY": None})
        assert result["PASSWORD"] is None
        assert result["API_KEY"] is None

    def test_redacts_url_credentials(self):
        """Strip userinfo segments from URL-shaped strings."""
        assert _redact_string("postgres://user:pw@host:5432/db") == (
            f"postgres://{REDACTED_PLACEHOLDER}@host:5432/db"
        )
        assert _redact_string("redis://:secretpw@redis:6379/0") == (
            f"redis://{REDACTED_PLACEHOLDER}@redis:6379/0"
        )
        assert (
            _redact_string("https://service_token:glsa_xyz@192.168.122.10/nomad")
            == f"https://{REDACTED_PLACEHOLDER}@192.168.122.10/nomad"
        )

    def test_redact_preserves_plain_urls(self):
        """Do not touch URLs that carry no credentials."""
        assert _redact_string("https://example.com/path") == "https://example.com/path"

    def test_redact_strips_url_creds_inside_nested_structure(self):
        """Scrub credential-laden URLs even when not under a sensitive key."""
        data = {"BROKER_URL": "amqp://guest:guest@broker:5672/"}
        result = redact(data)
        assert f"{REDACTED_PLACEHOLDER}@broker" in result["BROKER_URL"]
        assert "guest:guest" not in result["BROKER_URL"]

    def test_sensitive_patterns_constant_exposed(self):
        """Guard against accidental removal of denylist entries."""
        for needed in ("secret", "password", "api_key", "token"):
            assert needed in SENSITIVE_KEY_PATTERNS


class TestCollectEffectiveConfig:
    """Tests for :func:`collect_effective_config`."""

    def test_layout_mirrors_settings_yaml(self):
        """Produce a dict whose top-level keys match ``settings.yaml``."""
        config = collect_effective_config()
        for key in ("CASDOOR", "PMM", "CELERY", "SEP", "INVENTORY", "TASKS"):
            assert key in config, f"missing top-level key {key}"

    def test_nested_app_settings_placed_under_prefixes(self):
        """Nest plugin-scoped settings under their parent prefix."""
        config = collect_effective_config()
        assert isinstance(config["TASKS"], dict)
        assert "PERIODIC" in config["TASKS"]
        assert "ANONYMIZER" in config["TASKS"]
        assert isinstance(config["SEP"], dict)
        assert "SNIPPETS" in config["SEP"]

    def test_output_is_yaml_safe(self):
        """Ensure every dumped value survives a YAML round-trip."""
        config = redact(collect_effective_config())
        serialized = yaml.safe_dump(config)
        assert yaml.safe_load(serialized) == config

    def test_logging_config_and_base_dir_excluded(self):
        """Omit noisy or derived fields from the export."""
        config = collect_effective_config()
        assert "LOGGING_CONFIG" not in config
        assert "BASE_DIR" not in config


class TestExportConfigEndpoint:
    """Tests for the ``GET /admin/config/export`` endpoint."""

    def test_admin_receives_yaml_download(self, admin_test_client):
        """Return 200 with YAML body and attachment headers for admins."""
        response = admin_test_client.get("/admin/config/export")
        assert response.status_code == HTTP_200_OK
        assert response.headers["content-type"].startswith("application/yaml")
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        expected = f'attachment; filename="sep-config-{today}.yaml"'
        assert response.headers["content-disposition"] == expected

    def test_response_body_is_parseable_yaml(self, admin_test_client):
        """Ensure the response body is a valid YAML mapping."""
        response = admin_test_client.get("/admin/config/export")
        assert response.status_code == HTTP_200_OK
        parsed = yaml.safe_load(response.content)
        assert isinstance(parsed, dict)
        for key in ("SEP", "INVENTORY", "TASKS", "CASDOOR"):
            assert key in parsed

    def test_sensitive_fields_are_redacted(self, admin_test_client):
        """Values under sensitive keys never leak into the YAML body."""
        response = admin_test_client.get("/admin/config/export")
        parsed = yaml.safe_load(response.content)

        def _walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if any(p in key.lower() for p in SENSITIVE_KEY_PATTERNS):
                        assert value in (None, REDACTED_PLACEHOLDER), (
                            f"sensitive key {key!r} not redacted: {value!r}"
                        )
                    _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(parsed)

    def test_non_admin_is_denied(self, test_client):
        """Regular users are redirected by the default exception handler."""
        response = test_client.get("/admin/config/export", follow_redirects=False)
        assert response.status_code == HTTP_303_SEE_OTHER

    def test_unauthenticated_redirects_to_login(self):
        """Unauthenticated requests redirect to the login page."""
        sep_app.dependency_overrides = {}
        client = TestClient(sep_app, raise_server_exceptions=False)
        response = client.get("/admin/config/export", follow_redirects=False)
        assert response.status_code == HTTP_303_SEE_OTHER
        assert "/login" in response.headers.get("location", "")
