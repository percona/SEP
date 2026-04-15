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

"""Define tests for the app.core.config module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import (
    BaseYamlAppSettings,
    default_lifespan,
    PMMSettings,
    Settings,
    settings,
    YamlPrefixConfigSettingsSource,
)

DEFAULT_ANNOTATIONS_TIMEOUT = 5
CUSTOM_ANNOTATIONS_TIMEOUT = 7


class DummySettings(BaseSettings):
    """Define dummy settings class for testing purposes."""

    model_config = SettingsConfigDict(env_prefix="DUMMY_")


@pytest.fixture
def mock_yaml_data():
    """Provide mock YAML data for testing."""
    return {
        "default": {"key1": "default_value1", "key2": "default_value2"},
        "env1": {"key1": "env1_value1", "nested": {"key2": "env1_nested_value2"}},
        "env2": {
            "key3": "env2_value3",
            "nested": {"key2": "env2_nested_value2", "key4": "env2_nested_value4"},
        },
    }


@pytest.fixture
def mock_yaml_file(tmp_path, mock_yaml_data):
    """Create a temporary mock YAML file for testing."""
    yaml_file = tmp_path / "settings.yaml"
    import yaml

    with yaml_file.open("w") as f:
        yaml.dump(mock_yaml_data, f)
    return yaml_file


def test_yaml_prefix_config_settings_source_multiple_prefixes(mock_yaml_file):
    """Test YamlPrefixConfigSettingsSource with multiple prefixes."""
    prefixes = ("env2", "nested")
    base_prefix = "default"

    settings_source = YamlPrefixConfigSettingsSource(
        DummySettings,
        yaml_file=mock_yaml_file,
        prefixes=prefixes,
        base_prefix=base_prefix,
    )

    expected_data = {
        "key2": "env2_nested_value2",
        "key4": "env2_nested_value4",
    }

    assert settings_source.yaml_data == expected_data, (
        f"Expected {expected_data} but got {settings_source.yaml_data}"
    )


class MockSettings(BaseSettings):
    """Define mock settings class for testing."""


@pytest.fixture
def mock_env_settings():
    """Mock for environment settings."""
    env_settings = MagicMock()
    env_settings.env_vars = {
        "prefix__UVICORN_HOST": "0.0.0.0",
        "prefix__UVICORN_PORT": "8000",
    }
    return env_settings


@pytest.fixture
def mock_dotenv_settings():
    """Mock for dotenv settings."""
    dotenv_settings = MagicMock()
    dotenv_settings.env_vars = {
        "prefix__SSL_KEYFILE": "/path/to/keyfile",
        "prefix__SSL_CERTFILE": "/path/to/certfile",
    }
    return dotenv_settings


@pytest.fixture
def mock_yaml_prefix_source():
    """Mock for YAML settings source."""
    yaml_prefix_source = MagicMock()
    yaml_prefix_source.return_value = {
        "UVICORN_HOST": "127.0.0.1",
        "UVICORN_PORT": 8080,
    }
    return yaml_prefix_source


@pytest.fixture
def settings_class():
    """Mock settings class."""

    class TestSettings(BaseYamlAppSettings):
        SETTINGS_PREFIXES = ["prefix"]

    return TestSettings


@pytest.fixture
def mock_file_secret_settings():
    """Mock for file secret settings."""
    file_secret_settings = MagicMock()
    file_secret_settings.env_vars = {
        "prefix__SOME_SECRET": "supersecret",
    }
    return file_secret_settings


def test_settings_customise_sources(
    settings_class,
    mock_env_settings,
    mock_dotenv_settings,
    mock_file_secret_settings,
    mock_yaml_prefix_source,
):
    """Test the settings_customise_sources method."""
    settings_cls = settings_class

    customised_sources = settings_cls.settings_customise_sources(
        MockSettings,
        mock_yaml_prefix_source,
        mock_env_settings,
        mock_dotenv_settings,
        mock_file_secret_settings,
    )

    expected_length = 4
    assert isinstance(customised_sources, tuple)
    assert len(customised_sources) == expected_length

    processed_env_vars = customised_sources[1].env_vars
    assert "UVICORN_HOST" in processed_env_vars
    assert "UVICORN_PORT" in processed_env_vars
    assert processed_env_vars["UVICORN_HOST"] == "0.0.0.0"
    assert processed_env_vars["UVICORN_PORT"] == "8000"

    processed_dotenv_vars = customised_sources[2].env_vars
    assert "SSL_KEYFILE" in processed_dotenv_vars
    assert "SSL_CERTFILE" in processed_dotenv_vars
    assert processed_dotenv_vars["SSL_KEYFILE"] == "/path/to/keyfile"
    assert processed_dotenv_vars["SSL_CERTFILE"] == "/path/to/certfile"


@pytest.mark.asyncio
async def test_default_lifespan():
    """Test default_lifespan manages CASDOOR and closes sessions."""
    mock_casdoor = AsyncMock()
    mock_close_registry = AsyncMock()

    with (
        patch.object(Settings, "close_client_registry", mock_close_registry),
        patch("app.core.config.settings.CASDOOR", mock_casdoor),
    ):
        app = FastAPI()

        async with default_lifespan(app):
            pass

    mock_casdoor.__aenter__.assert_called_once()
    mock_casdoor.__aexit__.assert_called_once()
    mock_close_registry.assert_called_once()


def test_uvicorn_reload_defaults_to_false():
    """Assert ``UVICORN_RELOAD`` defaults to ``False`` on ``BaseYamlAppSettings``."""
    assert BaseYamlAppSettings.model_fields["UVICORN_RELOAD"].default is False


@pytest.mark.parametrize(
    "field_name",
    [
        "UVICORN_EXTRA_RELOAD_DIRS",
        "UVICORN_EXTRA_RELOAD_INCLUDES",
        "UVICORN_EXTRA_RELOAD_EXCLUDES",
    ],
)
def test_uvicorn_extra_reload_fields_default_to_empty_list(field_name: str):
    """Assert extra reload fields default to empty lists on ``BaseYamlAppSettings``."""
    field_info = BaseYamlAppSettings.model_fields[field_name]
    assert field_info.default == []


@pytest.mark.parametrize(
    ("field_name", "extra_values"),
    [
        ("UVICORN_EXTRA_RELOAD_DIRS", ["/extra/dir1", "/extra/dir2"]),
        ("UVICORN_EXTRA_RELOAD_INCLUDES", ["*.toml", "*.yaml"]),
        ("UVICORN_EXTRA_RELOAD_EXCLUDES", ["*.log", "*.tmp"]),
    ],
)
def test_uvicorn_extra_reload_fields_accept_nonempty_lists(field_name, extra_values):
    """Assert extra reload fields store non-empty values on ``BaseYamlAppSettings``."""
    instance = BaseYamlAppSettings.model_construct(**{field_name: extra_values})
    assert getattr(instance, field_name) == extra_values


class TestPMMSettings:
    """Test the core ``PMMSettings`` model."""

    def test_defaults_all_none_or_true(self):
        """Assert all fields default to ``None`` or ``True``."""
        pmm = PMMSettings()
        assert pmm.endpoint is None
        assert pmm.frontend is None
        assert pmm.api_key is None
        assert pmm.verify_ssl is True
        assert pmm.execution_target is None
        assert pmm.annotations_timeout == DEFAULT_ANNOTATIONS_TIMEOUT

    def test_hostname_extracted_from_endpoint(self):
        """Assert ``hostname`` extracts the host from the endpoint URL."""
        pmm = PMMSettings(endpoint="https://pmm.example.com:8443/path")
        assert pmm.hostname == "pmm.example.com"

    def test_hostname_none_when_no_endpoint(self):
        """Assert ``hostname`` is ``None`` when endpoint is not set."""
        pmm = PMMSettings()
        assert pmm.hostname is None

    def test_api_key_masked_in_repr(self):
        """Assert ``api_key`` is masked in repr output."""
        pmm = PMMSettings(api_key="my-secret-key")
        assert "my-secret-key" not in repr(pmm)

    def test_api_key_accepts_secretstr(self):
        """Assert ``PMMSettings`` accepts a string for ``api_key``."""
        pmm = PMMSettings(api_key="test-key")
        assert pmm.api_key.get_secret_value() == "test-key"

    def test_lowercases_yaml_keys(self):
        """Assert uppercase YAML keys are normalized to lowercase."""
        pmm = PMMSettings.model_validate(
            {
                "ENDPOINT": "https://pmm.example.com",
                "VERIFY_SSL": False,
                "ANNOTATIONS_TIMEOUT": CUSTOM_ANNOTATIONS_TIMEOUT,
            }
        )
        assert pmm.endpoint == "https://pmm.example.com"
        assert pmm.verify_ssl is False
        assert pmm.annotations_timeout == CUSTOM_ANNOTATIONS_TIMEOUT

    def test_ignores_extra_fields(self):
        """Assert extra fields are silently ignored."""
        pmm = PMMSettings.model_validate(
            {"endpoint": "https://pmm.example.com", "unknown_field": "value"}
        )
        assert pmm.endpoint == "https://pmm.example.com"
        assert not hasattr(pmm, "unknown_field")

    def test_frontend_defaults_to_endpoint(self):
        """Assert ``frontend`` defaults to ``endpoint`` when not explicitly set."""
        pmm = PMMSettings(endpoint="https://pmm.example.com")
        assert pmm.frontend == "https://pmm.example.com"

    def test_frontend_not_overridden_when_set(self):
        """Assert ``frontend`` is not overridden when explicitly set."""
        pmm = PMMSettings(
            endpoint="https://pmm.example.com",
            frontend="https://pmm-frontend.example.com",
        )
        assert pmm.frontend == "https://pmm-frontend.example.com"

    def test_frontend_stays_none_when_no_endpoint(self):
        """Assert ``frontend`` stays ``None`` when endpoint is also ``None``."""
        pmm = PMMSettings()
        assert pmm.frontend is None

    def test_settings_has_pmm_field(self):
        """Assert the global ``Settings`` class has a ``PMM`` field."""
        assert "PMM" in Settings.model_fields
        assert Settings.model_fields["PMM"].default == PMMSettings()


def test_settings_secret_key_is_secretstr():
    """Test that SECRET_KEY is a SecretStr instance and masked in repr."""
    from pydantic import SecretStr

    assert isinstance(settings.SECRET_KEY, SecretStr)
    secret_value = settings.SECRET_KEY.get_secret_value()
    if secret_value:
        assert secret_value not in repr(settings.SECRET_KEY)
