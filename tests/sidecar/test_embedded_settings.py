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
"""Tests for the baked PMM-embedded settings profile."""

import re
from typing import Any

import pytest

from app import BASE_DIR
from app.core.auth.config import AuthSettings
from app.core.config import Settings
from app.inventory.config import InventorySettings
from app.sep.apps.framework.registry import build_app_registry
from app.sep.config import SEPSettings
from app.tasks.config import TasksSettings
from tests.sidecar.conftest import EMBEDDED_PROFILE, SETTINGS_ENV_HELPER, SIDECAR_DIR

PASSWORD_BEARING_USERINFO = re.compile(r"://[^/@\s]+:[^/@\s]+@")
"""Match a URL whose authority carries both a user and a password.

Passwordless userinfo is legitimate here -- the profile's ``BEAT_DBURI`` is
``postgresql://sep@pmm-server:5432/sep`` -- so an ``@``-rejecting pattern would
fail against the very file it validates.
"""

PLACEHOLDER_MARKER = re.compile(r"glsa_|__[A-Z_]+__")
SECRET_KEYS = frozenset({"password", "service_account_token", "api_key"})

SHARED_DATABASE_NAME = "sep"
"""The one database PMM's ``PMM_ENABLE_SEP`` provisions for all three services."""

UNCOMPARABLE_FIELDS = frozenset({"FASTAPI_ENV", "JINJA_ENVIRONMENT", "TEMPLATES"})
"""Fields a dump comparison cannot use.

``FASTAPI_ENV`` is what the comparison varies; the other two are computed per
construction and compare by identity, so two instances never match on them.
"""


def uncommented(text: str) -> str:
    """Return ``text`` without its whole-line comments.

    The profile's comments name canonical environment variables such as
    ``TASKS__NOMAD__ENDPOINT``, which a placeholder scan over the raw text would
    read as a ``__MARKER__``.

    :param text: The profile source.
    :return: The source lines that carry configuration.
    :rtype: str
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def secret_valued_leaves(data: Any) -> list[tuple[str, Any]]:
    """Collect every secret-typed key/value pair at any depth of ``data``.

    :param data: A node of the parsed profile.
    :return: The secret-typed keys paired with their configured values.
    :rtype: list[tuple[str, Any]]
    """
    if isinstance(data, dict):
        return [
            *(
                (key, value)
                for key, value in data.items()
                if key.lower() in SECRET_KEYS
            ),
            *(pair for value in data.values() for pair in secret_valued_leaves(value)),
        ]
    if isinstance(data, list):
        return [pair for item in data for pair in secret_valued_leaves(item)]
    return []


def resolved_profile() -> dict[str, dict[str, Any]]:
    """Return every prefixed settings class as resolved from the profile.

    :return: The resolved settings, keyed by service.
    :rtype: dict[str, dict[str, Any]]
    """
    return {
        "global": Settings().model_dump(exclude=UNCOMPARABLE_FIELDS),
        "sep": SEPSettings().model_dump(exclude=UNCOMPARABLE_FIELDS),
        "inventory": InventorySettings().model_dump(exclude=UNCOMPARABLE_FIELDS),
        "tasks": TasksSettings().model_dump(exclude=UNCOMPARABLE_FIELDS),
    }


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_profile_constructs_every_settings_class():
    """Every settings class the side-car builds resolves from the profile alone."""
    assert Settings().CELERY.broker_url
    assert AuthSettings().PROVIDER
    assert SEPSettings().DATABASE.NAME == SHARED_DATABASE_NAME
    assert InventorySettings().DATABASE.NAME == SHARED_DATABASE_NAME
    assert TasksSettings().NOMAD.endpoint


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_pmm_annotations_stay_enabled_without_an_api_key():
    """Annotations are configured on, and inert, until a token is supplied."""
    settings = Settings()

    assert settings.PMM.annotations_enabled is True
    assert settings.PMM.api_key is None


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_grafana_provider_constructs_with_an_empty_token():
    """The provider is configured but inert until ``SEP_GRAFANA_TOKEN`` arrives."""
    provider = AuthSettings().PROVIDER["grafana"]

    assert provider.service_account_token.get_secret_value() == ""


def test_profile_carries_a_single_default_block(embedded_profile_data):
    """One block keeps the profile independent of the selected ``FASTAPI_ENV``."""
    assert set(embedded_profile_data) == {"default"}


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_exactly_one_auth_provider_is_configured():
    """A second provider copy would trip ``AuthSettings._exactly_one_provider``."""
    assert list(AuthSettings().PROVIDER) == ["grafana"]


def test_no_url_carries_a_password():
    """No URL in the profile embeds credentials in its authority."""
    profile = uncommented(EMBEDDED_PROFILE.read_text(encoding="utf-8"))

    assert PASSWORD_BEARING_USERINFO.search(profile) is None
    assert "postgresql://sep@pmm-server:5432/sep" in profile


def test_every_secret_typed_field_is_empty(embedded_profile_data):
    """Secret-typed keys are present only as empty values."""
    assert [
        (key, value)
        for key, value in secret_valued_leaves(embedded_profile_data)
        if value != ""
    ] == []


def test_no_placeholder_markers_remain():
    """The profile is a working default, not a template awaiting substitution."""
    profile = uncommented(EMBEDDED_PROFILE.read_text(encoding="utf-8"))

    assert PLACEHOLDER_MARKER.search(profile) is None


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_database_password_merges_into_the_profile_block(
    monkeypatch: pytest.MonkeyPatch,
):
    """An environment password lands without displacing the YAML siblings."""
    monkeypatch.setenv("SEP__DATABASE__PASSWORD", "pw")

    database = SEPSettings().DATABASE

    assert database.PASSWORD.get_secret_value() == "pw"
    assert (database.HOST, database.NAME, database.USER) == ("pmm-server", "sep", "sep")


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_grafana_token_merges_into_the_profile_block(monkeypatch: pytest.MonkeyPatch):
    """An environment token lands without displacing the YAML siblings."""
    monkeypatch.setenv("AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN", "glsa_x")

    provider = AuthSettings().PROVIDER["grafana"]

    assert provider.service_account_token.get_secret_value() == "glsa_x"
    assert str(provider.endpoint) == "https://pmm-server:8443/graph"
    assert provider.session_cookie_name == "pmm_session"
    assert provider.verify_ssl is False


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_activation_list_builds_an_app_registry():
    """The baked activation list satisfies every declared app dependency."""
    registry = build_app_registry(SEPSettings().APPS)

    assert {"inventory", "snippets", "atw", "mysql_backups"} <= set(registry.keys())


def test_uvicorn_ports_match_the_healthcheck_probe(embedded_profile_cwd):
    """The probe's hardcoded ports are image contract, so the profile follows them."""
    healthcheck = (SIDECAR_DIR / "healthcheck.sh").read_text(encoding="utf-8")
    probed = re.search(r"for port in \(([^)]*)\)", healthcheck)

    assert probed is not None
    assert [int(port) for port in probed.group(1).split(",")] == [
        SEPSettings().UVICORN_PORT,
        InventorySettings().UVICORN_PORT,
        TasksSettings().UVICORN_PORT,
    ]


def test_database_host_and_port_match_the_expansion_defaults(embedded_profile_cwd):
    """The profile and the entrypoint expansion state one truth about the server."""
    helper = SETTINGS_ENV_HELPER.read_text(encoding="utf-8")
    database = SEPSettings().DATABASE

    assert re.search(r"SEP_DB_HOST:-([^}\"]+)", helper).group(1) == database.HOST
    assert re.search(r"SEP_DB_PORT:-([^}\"]+)", helper).group(1) == str(database.PORT)


def test_profile_is_not_shipped_in_the_shared_bundle():
    """``make pack`` feeds both images, so the profile stays a side-car-only copy."""
    pack_recipe = re.search(
        r"^\s*@?git archive .*$",
        (BASE_DIR / "Makefile").read_text(encoding="utf-8"),
        re.MULTILINE,
    )

    assert pack_recipe is not None
    assert "settings.yaml" not in pack_recipe.group(0)


def test_profile_resolves_identically_outside_production_docker(
    embedded_profile_cwd, monkeypatch: pytest.MonkeyPatch
):
    """A single block leaves nothing for the ``FASTAPI_ENV`` selection to change."""
    baked = resolved_profile()
    monkeypatch.setenv("FASTAPI_ENV", "development")

    assert resolved_profile() == baked
