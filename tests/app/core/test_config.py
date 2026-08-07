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

import hashlib
import hmac
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from pydantic import AliasChoices, Field, SecretStr, ValidationError
from pydantic_settings import (
    BaseSettings,
    NestedSecretsSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.exceptions import SettingsError
from pydantic_settings.sources import (
    DotEnvSettingsSource,
    EnvSettingsSource,
    InitSettingsSource,
)

from app.core.alerts.config import AlertSettings
from app.core.auth.config import AuthSettings
from app.core.config import (
    _sanitize_client_kwargs,
    BaseYamlAppSettings,
    create_app,
    default_lifespan,
    PMMSettings,
    PreEnvSettings,
    Settings,
    settings,
    YamlPrefixConfigSettingsSource,
)
from app.inventory.config import InventorySettings
from app.sep.apps.alerts.config import AlertsSettings
from app.sep.apps.atw.config import AtwSettings
from app.sep.config import SEPSettings
from app.sep.middleware.messages.config import MessagesSettings
from app.sep.middleware.messages.models import MessageLevel
from app.sep.snippets.config import SnippetsSettings
from app.tasks.anonymizer.config import AnonymizerSettings
from app.tasks.config import TasksSettings

DEFAULT_ANNOTATIONS_TIMEOUT = 5
CUSTOM_ANNOTATIONS_TIMEOUT = 7


def test_sanitize_client_kwargs_redacts_url_password():
    """``_sanitize_client_kwargs`` masks a password embedded in an endpoint URL."""
    safe = _sanitize_client_kwargs(
        {
            "endpoint": "http://user:hunter2@localhost:8000/",
            "verify_ssl": False,
        }
    )
    assert "hunter2" not in safe["endpoint"]
    assert "****" in safe["endpoint"]
    assert safe["verify_ssl"] is False


def test_sanitize_client_kwargs_preserves_credential_free_values():
    """``_sanitize_client_kwargs`` leaves non-credential values untouched."""
    api_key = SecretStr("token")
    safe = _sanitize_client_kwargs(
        {"endpoint": "http://localhost:8000/", "api_key": api_key}
    )
    assert safe["endpoint"] == "http://localhost:8000/"
    assert safe["api_key"] is api_key


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
def file_secret_settings(settings_class, tmp_path):
    """Provide a real file-secret source over a directory holding one prefixed secret.

    A ``MagicMock`` cannot stand in here: ``NestedSecretsSettingsSource`` reads
    ``settings_cls.model_config`` and rejects the ``MagicMock`` that every
    ``conf.get(...)`` returns with an opaque ``SettingsError``.
    """
    (tmp_path / "prefix__SOME_SECRET").write_text("supersecret", encoding="utf-8")
    return SecretsSettingsSource(settings_class, secrets_dir=tmp_path)


def test_settings_customise_sources(
    settings_class,
    mock_env_settings,
    mock_dotenv_settings,
    file_secret_settings,
    mock_yaml_prefix_source,
):
    """Test the settings_customise_sources method."""
    settings_cls = settings_class

    customised_sources = settings_cls.settings_customise_sources(
        MockSettings,
        mock_yaml_prefix_source,
        mock_env_settings,
        mock_dotenv_settings,
        file_secret_settings,
    )

    expected_length = 5
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

    secret_source = customised_sources[3]
    assert isinstance(secret_source, NestedSecretsSettingsSource)
    assert secret_source.env_vars == {"some_secret": "supersecret"}


@pytest.mark.asyncio
async def test_default_lifespan():
    """Verify default_lifespan enters the active provider's lifespan and closes sessions."""
    mock_lifespan_cm = AsyncMock()
    mock_provider = MagicMock()
    mock_provider.lifespan.return_value = mock_lifespan_cm
    mock_close_registry = AsyncMock()

    with (
        patch.object(Settings, "close_client_registry", mock_close_registry),
        patch(
            "app.core.auth.config.get_active_auth_provider", return_value=mock_provider
        ),
    ):
        app = FastAPI()

        async with default_lifespan(app):
            pass

    mock_provider.lifespan.assert_called_once()
    mock_lifespan_cm.__aenter__.assert_called_once()
    mock_lifespan_cm.__aexit__.assert_called_once()
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
    assert isinstance(settings.SECRET_KEY, SecretStr)
    secret_value = settings.SECRET_KEY.get_secret_value()
    if secret_value:
        assert secret_value not in repr(settings.SECRET_KEY)


def test_create_app_default_docs_urls():
    """``create_app`` without docs kwargs preserves FastAPI's default docs URLs."""
    app = create_app()
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"


def test_create_app_disables_docs_when_none():
    """``create_app`` forwards ``docs_url=None`` and ``redoc_url=None`` to FastAPI."""
    app = create_app(docs_url=None, redoc_url=None)
    assert app.docs_url is None
    assert app.redoc_url is None


def test_create_app_custom_docs_url():
    """``create_app`` forwards a custom ``docs_url`` to FastAPI."""
    app = create_app(docs_url="/custom-docs", redoc_url="/custom-redoc")
    assert app.docs_url == "/custom-docs"
    assert app.redoc_url == "/custom-redoc"


class TestDeriveInternalToken:
    """Cover SEP_INTERNAL_TOKEN derivation from SECRET_KEY."""

    @staticmethod
    def _expected_token(secret_key: str) -> str:
        return hmac.new(
            secret_key.encode(), b"sep-internal-token", hashlib.sha256
        ).hexdigest()

    def test_explicit_token_takes_precedence(self):
        """An explicitly configured token is used verbatim, never derived."""
        instance = Settings(
            SECRET_KEY=SecretStr("any-secret"),
            SEP_INTERNAL_TOKEN=SecretStr("explicit-token"),
        )
        assert instance.SEP_INTERNAL_TOKEN.get_secret_value() == "explicit-token"

    def test_derives_from_secret_key_when_unset(self):
        """An unset token is derived as HMAC-SHA256 over the secret key."""
        instance = Settings(
            SECRET_KEY=SecretStr("derivation-secret"),
            SEP_INTERNAL_TOKEN=None,
        )
        assert instance.SEP_INTERNAL_TOKEN is not None
        assert instance.SEP_INTERNAL_TOKEN.get_secret_value() == self._expected_token(
            "derivation-secret"
        )

    def test_empty_token_is_derived(self):
        """An empty-string token is treated as unset and derived."""
        instance = Settings(
            SECRET_KEY=SecretStr("derivation-secret"),
            SEP_INTERNAL_TOKEN=SecretStr(""),
        )
        assert instance.SEP_INTERNAL_TOKEN.get_secret_value() == self._expected_token(
            "derivation-secret"
        )

    def test_derivation_is_identical_across_instances(self):
        """Two settings sharing a secret key derive the identical token."""
        first = Settings(SECRET_KEY=SecretStr("shared-secret"), SEP_INTERNAL_TOKEN=None)
        second = Settings(
            SECRET_KEY=SecretStr("shared-secret"), SEP_INTERNAL_TOKEN=None
        )
        assert (
            first.SEP_INTERNAL_TOKEN.get_secret_value()
            == second.SEP_INTERNAL_TOKEN.get_secret_value()
        )

    def test_empty_secret_key_without_token_raises(self):
        """An empty secret key with no explicit token fails fast at construction."""
        with pytest.raises(ValidationError, match="SECRET_KEY must be set"):
            Settings(SECRET_KEY=SecretStr(""), SEP_INTERNAL_TOKEN=None)


SECRET_FILE_MATRIX = [
    pytest.param(
        Settings,
        "SECRET_KEY",
        "matrix-secret-key",
        "matrix-secret-key",
        lambda s: s.SECRET_KEY.get_secret_value(),
        id="Settings",
    ),
    pytest.param(
        AlertSettings,
        "ALERTING__SOURCE_PREFIX",
        "matrix-prefix",
        "matrix-prefix",
        lambda s: s.SOURCE_PREFIX,
        id="AlertSettings",
    ),
    pytest.param(
        AuthSettings,
        "AUTH__PROVIDER__CASDOOR__CLIENT_SECRET",
        "matrix-client-secret",
        "matrix-client-secret",
        lambda s: s.PROVIDER["casdoor"].client_secret.get_secret_value(),
        id="AuthSettings",
    ),
    pytest.param(
        InventorySettings,
        "INVENTORY__DATABASE__PASSWORD",
        "matrix-inventory-pw",
        "matrix-inventory-pw",
        lambda s: s.DATABASE.PASSWORD.get_secret_value(),
        id="InventorySettings",
    ),
    pytest.param(
        SEPSettings,
        "SEP__DATABASE__PASSWORD",
        "matrix-sep-pw",
        "matrix-sep-pw",
        lambda s: s.DATABASE.PASSWORD.get_secret_value(),
        id="SEPSettings",
    ),
    pytest.param(
        AlertsSettings,
        "SEP__ALERTS__ALERT_FOLDER_NAME",
        "Matrix Folder",
        "Matrix Folder",
        lambda s: s.ALERT_FOLDER_NAME,
        id="AlertsSettings",
    ),
    pytest.param(
        AtwSettings,
        "SEP__ATW__BUNDLE_TTL",
        "77",
        77,
        lambda s: s.bundle_ttl,
        id="AtwSettings",
    ),
    pytest.param(
        MessagesSettings,
        "SEP__MESSAGES__LEVEL",
        str(MessageLevel.ERROR.value),
        MessageLevel.ERROR,
        lambda s: s.LEVEL,
        id="MessagesSettings",
    ),
    pytest.param(
        SnippetsSettings,
        "SEP__SNIPPETS__PREVIEW_MAX_CHARS",
        "123",
        123,
        lambda s: s.PREVIEW_MAX_CHARS,
        id="SnippetsSettings",
    ),
    pytest.param(
        TasksSettings,
        "TASKS__DATABASE__PASSWORD",
        "matrix-tasks-pw",
        "matrix-tasks-pw",
        lambda s: s.DATABASE.PASSWORD.get_secret_value(),
        id="TasksSettings",
    ),
    pytest.param(
        AnonymizerSettings,
        "TASKS__ANONYMIZER__NLP_MODELS",
        '{"en": "matrix_model"}',
        "matrix_model",
        lambda s: s.NLP_MODELS["en"],
        id="AnonymizerSettings",
    ),
]


@pytest.fixture
def aliased_settings_class():
    """Build a prefixed settings class whose field carries a validation alias.

    ``SEPSettings.APPS`` declares ``AliasChoices("APPS", "PLUGINS")``. An aliased
    field is looked up without ``env_prefix`` unless ``env_prefix_target`` opts in,
    so the source's native ``secrets_prefix`` would silently drop its secret file;
    the key-rewriting loop this class exercises is what makes it resolve.
    """

    class AliasedSettings(BaseYamlAppSettings):
        SETTINGS_PREFIXES = ["SEP"]
        APPS: list[str] = Field(
            default_factory=list,
            validation_alias=AliasChoices("APPS", "PLUGINS"),
        )

    return AliasedSettings


def test_unprefixed_class_reads_secret_file(tmp_path):
    """Resolve an unprefixed setting from a file named after its canonical variable."""
    (tmp_path / "SECRET_KEY").write_text("from-file\n", encoding="utf-8")

    instance = Settings(_secrets_dir=tmp_path)

    assert instance.SECRET_KEY.get_secret_value() == "from-file"


def test_prefixed_class_reads_nested_secret_file(tmp_path):
    """Resolve a nested setting on a prefixed class from its canonical file name."""
    (tmp_path / "INVENTORY__DATABASE__PASSWORD").write_text(
        "inventory-pw", encoding="utf-8"
    )

    instance = InventorySettings(_secrets_dir=tmp_path)

    assert instance.DATABASE.PASSWORD.get_secret_value() == "inventory-pw"


def test_aliased_field_resolves_from_secret_file(tmp_path, aliased_settings_class):
    """Resolve a prefixed secret file for a field declaring a validation alias."""
    (tmp_path / "SEP__APPS").write_text('["alerts"]', encoding="utf-8")

    instance = aliased_settings_class(_secrets_dir=tmp_path)

    assert instance.APPS == ["alerts"]


def test_sep_settings_reads_aliased_secret_file(tmp_path):
    """Resolve ``SEP__APPS`` from a file through the production override of the hook."""
    (tmp_path / "SEP__APPS").write_text(
        '[{"module_name": "tasks", "uri_path": "/tasks"}]', encoding="utf-8"
    )

    instance = SEPSettings(_secrets_dir=tmp_path)

    assert [app.module_name for app in instance.APPS] == ["app.sep.apps.tasks"]


def test_file_backed_legacy_plugins_key_does_not_warn(tmp_path):
    """Populate the app list from a ``SEP__PLUGINS`` file without deprecating it.

    ``SEPSettings.settings_customise_sources`` inspects only the environment and
    dotenv sources, so the file-backed spelling is outside the deprecation
    contract even though the alias still resolves it.
    """
    (tmp_path / "SEP__PLUGINS").write_text(
        '[{"module_name": "tasks", "uri_path": "/tasks"}]', encoding="utf-8"
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        instance = SEPSettings(_secrets_dir=tmp_path)

    assert [app.module_name for app in instance.APPS] == ["app.sep.apps.tasks"]
    assert not [w for w in caught if "PLUGINS" in str(w.message)]


def test_env_var_beats_secret_file(tmp_path, monkeypatch):
    """Prefer an environment variable over a same-named secret file."""
    (tmp_path / "INVENTORY__DATABASE__PASSWORD").write_text(
        "from-file", encoding="utf-8"
    )
    monkeypatch.setenv("INVENTORY__DATABASE__PASSWORD", "from-env")

    instance = InventorySettings(_secrets_dir=tmp_path)

    assert instance.DATABASE.PASSWORD.get_secret_value() == "from-env"


def test_dotenv_entry_beats_secret_file(tmp_path):
    """Prefer a dotenv entry over a same-named secret file."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "INVENTORY__DATABASE__PASSWORD").write_text(
        "from-file", encoding="utf-8"
    )
    env_file = tmp_path / "dotenv"
    env_file.write_text("INVENTORY__DATABASE__PASSWORD=from-dotenv\n", encoding="utf-8")

    instance = InventorySettings(_secrets_dir=secrets_dir, _env_file=env_file)

    assert instance.DATABASE.PASSWORD.get_secret_value() == "from-dotenv"


def test_secret_file_beats_yaml_profile(tmp_path):
    """Prefer a secret file over the value the baked YAML profile supplies."""
    baseline = Settings()
    (tmp_path / "SECRET_KEY").write_text("from-file", encoding="utf-8")

    instance = Settings(_secrets_dir=tmp_path)

    assert baseline.SECRET_KEY.get_secret_value() != "from-file"
    assert instance.SECRET_KEY.get_secret_value() == "from-file"


def test_full_precedence_chain(tmp_path, monkeypatch):
    """Resolve one key at every level of the chain, each beating the ones after it."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "INVENTORY__DATABASE__PASSWORD").write_text(
        "from-file", encoding="utf-8"
    )
    env_file = tmp_path / "dotenv"
    env_file.write_text("INVENTORY__DATABASE__PASSWORD=from-dotenv\n", encoding="utf-8")

    def build(**kwargs):
        return InventorySettings(
            _secrets_dir=secrets_dir, _env_file=env_file, **kwargs
        ).DATABASE.PASSWORD.get_secret_value()

    monkeypatch.setenv("INVENTORY__DATABASE__PASSWORD", "from-env")
    assert build(DATABASE={"PASSWORD": "from-init"}) == "from-init"
    assert build() == "from-env"

    monkeypatch.delenv("INVENTORY__DATABASE__PASSWORD")
    assert build() == "from-dotenv"

    env_file.write_text("", encoding="utf-8")
    assert build() == "from-file"


def test_unset_secrets_dir_resolves_as_before():
    """Resolve every setting unchanged, and warn about nothing, with the knob unset."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        instance = Settings()

    assert (
        instance.SECRET_KEY.get_secret_value()
        == Settings().SECRET_KEY.get_secret_value()
    )
    assert not caught


def test_empty_secrets_dir_env_value_coerces_to_none(monkeypatch):
    """Coerce an empty ``SECRETS_DIR`` to ``None`` so the source never walks the CWD."""
    monkeypatch.setenv("SECRETS_DIR", "")

    assert PreEnvSettings().SECRETS_DIR is None


def test_missing_secrets_dir_warns_and_degrades(tmp_path):
    """Degrade to the profile value with one warning when the directory is absent."""
    absent = tmp_path / "absent"

    with pytest.warns(UserWarning, match="does not exist"):
        instance = Settings(_secrets_dir=absent)

    assert (
        instance.SECRET_KEY.get_secret_value()
        == Settings().SECRET_KEY.get_secret_value()
    )


def test_secrets_dir_without_matching_file_resolves_defaults(tmp_path):
    """Fall through to the profile when the directory holds no matching file."""
    (tmp_path / "UNRELATED_KEY").write_text("ignored", encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        instance = Settings(_secrets_dir=tmp_path)

    assert (
        instance.SECRET_KEY.get_secret_value()
        == Settings().SECRET_KEY.get_secret_value()
    )
    assert not caught


def test_empty_secret_file_overrides_profile_value(tmp_path):
    """Resolve an empty secret file to ``""`` rather than falling back to the profile."""
    (tmp_path / "INVENTORY__UVICORN_HOST").write_text("", encoding="utf-8")

    instance = InventorySettings(_secrets_dir=tmp_path)

    assert instance.UVICORN_HOST == ""


def test_secret_file_content_is_stripped(tmp_path):
    """Strip surrounding whitespace so ``openssl rand -hex 32 > FILE`` works as written."""
    (tmp_path / "INVENTORY__UVICORN_HOST").write_text("  padded  \n", encoding="utf-8")

    instance = InventorySettings(_secrets_dir=tmp_path)

    assert instance.UVICORN_HOST == "padded"


def test_secrets_dir_pointing_at_a_file_fails_fast(tmp_path):
    """Reject a ``SECRETS_DIR`` that names a file instead of a directory."""
    not_a_dir = tmp_path / "afile"
    not_a_dir.write_text("content", encoding="utf-8")

    with pytest.raises(SettingsError, match="must reference a directory"):
        Settings(_secrets_dir=not_a_dir)


def test_oversized_secrets_dir_fails_fast(tmp_path):
    """Reject a secrets directory whose contents exceed the size ceiling."""
    (tmp_path / "OVERSIZED").write_bytes(b"x" * (16 * 2**20 + 1))

    with pytest.raises(SettingsError, match="size is above"):
        Settings(_secrets_dir=tmp_path)


def test_secret_in_subdirectory_is_ignored(tmp_path):
    """Ignore a secret nested in a subdirectory, whose key can match no field."""
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "SECRET_KEY").write_text("nested-value", encoding="utf-8")

    instance = Settings(_secrets_dir=tmp_path)

    assert instance.SECRET_KEY.get_secret_value() != "nested-value"


def test_symlink_escaping_secrets_dir_is_ignored(tmp_path):
    """Ignore a symlink whose target resolves outside the secrets directory."""
    outside = tmp_path / "outside"
    outside.write_text("escaped-value", encoding="utf-8")
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "SECRET_KEY").symlink_to(outside)

    instance = Settings(_secrets_dir=secrets_dir)

    assert instance.SECRET_KEY.get_secret_value() != "escaped-value"


def test_kubernetes_projected_secret_resolves(tmp_path):
    """Resolve a secret through the ``..data`` symlink layout Kubernetes projects."""
    data_dir = tmp_path / "..data"
    data_dir.mkdir()
    (data_dir / "SECRET_KEY").write_text("projected-value", encoding="utf-8")
    (tmp_path / "SECRET_KEY").symlink_to(data_dir / "SECRET_KEY")

    instance = Settings(_secrets_dir=tmp_path)

    assert instance.SECRET_KEY.get_secret_value() == "projected-value"


def test_unprefixed_file_resolves_for_prefixed_class(tmp_path):
    """Resolve an unprefixed secret file for a prefixed class, as its env twin does."""
    (tmp_path / "DATABASE__PASSWORD").write_text("bare-pw", encoding="utf-8")

    instance = InventorySettings(_secrets_dir=tmp_path)

    assert instance.DATABASE.PASSWORD.get_secret_value() == "bare-pw"


def test_foreign_prefix_file_does_not_resolve(tmp_path):
    """Leave a class untouched by a secret file spelled with another class's prefix."""
    (tmp_path / "SEP__DATABASE__PASSWORD").write_text("sep-pw", encoding="utf-8")

    instance = InventorySettings(_secrets_dir=tmp_path)

    assert instance.DATABASE.PASSWORD is None


@pytest.mark.parametrize(
    ("settings_cls", "filename", "content", "expected", "read"), SECRET_FILE_MATRIX
)
def test_every_settings_class_reads_its_own_secret_file(
    tmp_path, monkeypatch, settings_cls, filename, content, expected, read
):
    """Resolve one secret file per concrete settings class, spelled with its own prefix."""
    monkeypatch.delenv(filename, raising=False)
    (tmp_path / filename).write_text(f"{content}\n", encoding="utf-8")

    assert read(settings_cls(_secrets_dir=tmp_path)) == expected


def test_grafana_token_file_maps_to_its_nested_field_path(tmp_path):
    """Rewrite the Grafana service-account-token file onto its nested field path.

    ``AuthSettings`` accepts exactly one provider and the shipped profile supplies
    Casdoor, so a Grafana-only instance cannot be built here — that invariant is
    identical for the variable's environment twin. What this ticket owns is the
    key the source hands the model, which is what this pins.
    """
    filename = "AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN"
    (tmp_path / filename).write_text("glsa_from_file\n", encoding="utf-8")

    sources = AuthSettings.settings_customise_sources(
        AuthSettings,
        InitSettingsSource(AuthSettings, init_kwargs={}),
        EnvSettingsSource(AuthSettings),
        DotEnvSettingsSource(AuthSettings, env_file=None),
        SecretsSettingsSource(AuthSettings, secrets_dir=tmp_path),
    )
    secret_source = next(
        source for source in sources if isinstance(source, NestedSecretsSettingsSource)
    )

    assert secret_source.env_vars == {
        "provider__grafana__service_account_token": "glsa_from_file"
    }


def _yaml_source_for(settings_cls, secrets_dir):
    """Return the YAML source ``settings_customise_sources`` builds for a secrets dir."""
    sources = settings_cls.settings_customise_sources(
        settings_cls,
        InitSettingsSource(settings_cls, init_kwargs={}),
        EnvSettingsSource(settings_cls),
        DotEnvSettingsSource(settings_cls, env_file=None),
        SecretsSettingsSource(settings_cls, secrets_dir=secrets_dir),
    )
    return next(
        source
        for source in sources
        if isinstance(source, YamlPrefixConfigSettingsSource)
    )


def test_secret_file_selects_the_yaml_profile(tmp_path, monkeypatch):
    """Select the YAML profile block a file-supplied ``FASTAPI_ENV`` names.

    ``FASTAPI_ENV`` both populates a field and picks the profile block. Reading it
    from only the environment and dotenv would let the two disagree — the settings
    reporting one environment while the values came from another's block.
    """
    (tmp_path / "FASTAPI_ENV").write_text("production_docker\n", encoding="utf-8")

    from_file = _yaml_source_for(Settings, tmp_path)

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("FASTAPI_ENV", "production_docker")
    from_env = _yaml_source_for(Settings, empty)

    assert from_file.yaml_data == from_env.yaml_data


def test_env_var_beats_secret_file_for_the_yaml_profile(tmp_path, monkeypatch):
    """Prefer the environment over a secret file when selecting the profile block."""
    (tmp_path / "FASTAPI_ENV").write_text("production_docker\n", encoding="utf-8")
    monkeypatch.setenv("FASTAPI_ENV", "development")

    empty = tmp_path / "empty"
    empty.mkdir()
    from_env = _yaml_source_for(Settings, tmp_path)
    baseline = _yaml_source_for(Settings, empty)

    assert from_env.yaml_data == baseline.yaml_data
