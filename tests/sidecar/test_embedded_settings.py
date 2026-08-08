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
from app.inventory.settings.routes import INVENTORY_ADMIN_SETTINGS_CLASSES
from app.sep.api.routes.settings import SEP_ADMIN_SETTINGS_CLASSES
from app.sep.apps.framework.registry import (
    build_app_registry,
    collect_app_owned_settings_classes,
)
from app.sep.config import SEPSettings
from app.tasks.config import TasksSettings
from app.tasks.settings.routes import TASKS_ADMIN_SETTINGS_CLASSES
from tests.sidecar.conftest import (
    EMBEDDED_PROFILE,
    read_allowlist,
    SETTINGS_ENV_HELPER,
    SIDECAR_DIR,
)

PASSWORD_BEARING_USERINFO = re.compile(r"://[^/@\s]+:[^/@\s]+@")
"""Match a URL whose authority carries both a user and a password.

Only an embedded credential is a finding, and a bare user in an authority is
legitimate, so an ``@``-rejecting pattern would be broader than the invariant
this file enforces.
"""

PLACEHOLDER_MARKER = re.compile(r"glsa_|__[A-Z_]+__")
SECRET_KEYS = frozenset({"password", "service_account_token", "api_key"})

SECRET_MAP_KEYS = frozenset({"secrets"})
"""Keys whose whole sub-mapping is secret-valued, whatever its members are named.

``DIAGNOSTICS_DELIVERY.secrets`` names its credentials after the receiver's own
fields (``sn_api_key``, ``client_token``), which :data:`SECRET_KEYS` would walk
past, so the block is matched by its container instead.
"""

SHARED_DATABASE_NAME = "sep"
"""The one database PMM's ``PMM_ENABLE_SEP`` provisions for all three services."""

ALLOWLIST_SIZE = 13
"""How many entries the embedded override allowlist ships.

Pinned so a silently truncated list -- which the policy suite's negative
assertions would still accept -- fails here instead.
"""

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
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def secret_valued_leaves(data: Any) -> list[tuple[str, Any]]:
    """Collect every secret-typed key/value pair at any depth of ``data``.

    :param data: A node of the parsed profile.
    :return: The secret-typed keys paired with their configured values.
    """
    if isinstance(data, dict):
        return [
            *(
                (key, value)
                for key, value in data.items()
                if key.lower() in SECRET_KEYS
            ),
            *(
                pair
                for key, value in data.items()
                if key.lower() in SECRET_MAP_KEYS and isinstance(value, dict)
                for pair in value.items()
            ),
            *(pair for value in data.values() for pair in secret_valued_leaves(value)),
        ]
    if isinstance(data, list):
        return [pair for item in data for pair in secret_valued_leaves(item)]
    return []


def resolved_profile() -> dict[str, dict[str, Any]]:
    """Return every prefixed settings class as resolved from the profile.

    :return: The resolved settings, keyed by service.
    """
    return {
        "global": Settings().model_dump(exclude=UNCOMPARABLE_FIELDS),
        "sep": SEPSettings().model_dump(exclude=UNCOMPARABLE_FIELDS),
        "inventory": InventorySettings().model_dump(exclude=UNCOMPARABLE_FIELDS),
        "tasks": TasksSettings().model_dump(exclude=UNCOMPARABLE_FIELDS),
    }


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_profile_constructs_every_settings_class():
    """Assert every settings class the side-car builds resolves from the profile."""
    assert Settings().CELERY.broker_url
    assert AuthSettings().PROVIDER
    assert SEPSettings().DATABASE.NAME == SHARED_DATABASE_NAME
    assert SEPSettings().DIAGNOSTICS_DELIVERY is not None
    assert InventorySettings().DATABASE.NAME == SHARED_DATABASE_NAME
    assert TasksSettings().NOMAD.endpoint


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_pmm_annotations_stay_enabled_without_an_api_key():
    """Assert annotations are configured on, and inert, until a token arrives."""
    settings = Settings()

    assert settings.PMM.annotations_enabled is True
    assert settings.PMM.api_key is None


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_connectivity_check_defaults_to_unchecked():
    """Assert the connectivity checkbox resolves unchecked from the profile.

    The profile allowlists ``CONNECTIVITY_CHECK_DEFAULT`` without setting it, so
    the resolved value is the declared field default -- which a repository
    checkout masks, because its own ``settings.yaml`` supplies one.
    """
    assert SEPSettings().CONNECTIVITY_CHECK_DEFAULT is False


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_grafana_provider_constructs_with_an_empty_token():
    """Assert the provider constructs, inert, until ``SEP_GRAFANA_TOKEN`` arrives."""
    provider = AuthSettings().PROVIDER["grafana"]

    assert provider.service_account_token.get_secret_value() == ""


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_override_allowlist_resolves_from_the_profile(embedded_profile_data: dict):
    """Assert the profile's YAML list coerces into the field the policy reads."""
    declared = read_allowlist(embedded_profile_data)

    assert len(declared) == ALLOWLIST_SIZE
    assert set(declared) == Settings().SETTINGS_OVERRIDE.ALLOWED_KEYS


def test_profile_carries_a_single_default_block(embedded_profile_data: dict):
    """Assert one block keeps the profile independent of ``FASTAPI_ENV``."""
    assert set(embedded_profile_data) == {"default"}


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_exactly_one_auth_provider_is_configured():
    """Reject a second provider copy, which trips the exactly-one-provider check."""
    assert list(AuthSettings().PROVIDER) == ["grafana"]


def test_no_url_carries_a_password():
    """Reject any URL embedding credentials in its authority."""
    profile = uncommented(EMBEDDED_PROFILE.read_text(encoding="utf-8"))

    assert PASSWORD_BEARING_USERINFO.search(profile) is None
    assert PASSWORD_BEARING_USERINFO.search("postgresql://u:p@h/db")


def test_the_profile_configures_no_beat_store():
    """Leave ``BEAT_DBURI`` unset, so the beat store follows the SEP database.

    A profile value is a configured value and would outrank the derived default,
    handing celery-beat a password-less URI. The assertion reads the uncommented
    text because the comment recording the omission names the key deliberately.
    """
    profile = uncommented(EMBEDDED_PROFILE.read_text(encoding="utf-8"))

    assert "BEAT_DBURI" not in profile


def test_every_secret_typed_field_is_empty(embedded_profile_data: dict):
    """Assert secret-typed keys are present only as empty values."""
    leaves = secret_valued_leaves(embedded_profile_data)

    assert leaves
    assert [(key, value) for key, value in leaves if value != ""] == []


def test_no_placeholder_markers_remain():
    """Reject placeholder markers: the profile is a default, not a template."""
    profile = uncommented(EMBEDDED_PROFILE.read_text(encoding="utf-8"))

    assert PLACEHOLDER_MARKER.search(profile) is None


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_database_password_merges_into_the_profile_block(
    monkeypatch: pytest.MonkeyPatch,
):
    """Assert an environment password lands without displacing its YAML siblings."""
    monkeypatch.setenv("SEP__DATABASE__PASSWORD", "pw")

    database = SEPSettings().DATABASE

    assert database.PASSWORD.get_secret_value() == "pw"
    assert (database.HOST, database.NAME, database.USER) == ("pmm-server", "sep", "sep")


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_grafana_token_merges_into_the_profile_block(monkeypatch: pytest.MonkeyPatch):
    """Assert an environment token lands without displacing its YAML siblings."""
    monkeypatch.setenv("AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN", "glsa_x")

    provider = AuthSettings().PROVIDER["grafana"]

    assert provider.service_account_token.get_secret_value() == "glsa_x"
    assert str(provider.endpoint) == "https://pmm-server:8443/graph"
    assert provider.session_cookie_name == "pmm_session"
    assert provider.verify_ssl is False


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_activation_list_builds_an_app_registry():
    """Assert the baked activation list satisfies every declared app dependency."""
    activated = set(build_app_registry(SEPSettings().APPS).keys())

    assert {"inventory", "atw", "mysql_backups"} <= activated
    assert "snippets" not in activated


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_uvicorn_ports_match_the_healthcheck_probe():
    """Assert the profile follows the probe's hardcoded ports, which are contract."""
    healthcheck = (SIDECAR_DIR / "healthcheck.sh").read_text(encoding="utf-8")
    probed = re.search(r"for port in \(([^)]*)\)", healthcheck)

    assert probed is not None
    assert [int(port) for port in probed.group(1).split(",")] == [
        SEPSettings().UVICORN_PORT,
        InventorySettings().UVICORN_PORT,
        TasksSettings().UVICORN_PORT,
    ]


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_database_host_and_port_match_the_expansion_defaults():
    """Assert the profile and the expansion state one truth about the server."""
    helper = SETTINGS_ENV_HELPER.read_text(encoding="utf-8")
    database = SEPSettings().DATABASE
    host = re.search(r"SEP_DB_HOST:-([^}\"]+)", helper)
    port = re.search(r"SEP_DB_PORT:-([^}\"]+)", helper)

    assert host is not None
    assert port is not None
    assert host.group(1) == database.HOST
    assert port.group(1) == str(database.PORT)


def test_profile_is_not_shipped_in_the_shared_bundle():
    """Assert the profile stays a side-car-only copy of the shared bundle."""
    pack_recipe = re.search(
        r"^\s*@?git archive .*$",
        (BASE_DIR / "Makefile").read_text(encoding="utf-8"),
        re.MULTILINE,
    )

    assert pack_recipe is not None
    assert "settings.yaml" not in pack_recipe.group(0)


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_profile_resolves_identically_outside_production_docker(
    monkeypatch: pytest.MonkeyPatch,
):
    """Assert the ``FASTAPI_ENV`` selection has nothing left to change."""
    baked = resolved_profile()
    monkeypatch.setenv("FASTAPI_ENV", "development")

    assert resolved_profile() == baked


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_every_allowlist_entry_names_a_reachable_class(embedded_profile_data: dict):
    """Assert every allowlist class token is reachable across all three services.

    The reachable set is the union of the SEP, Inventory and Tasks wired classes
    plus the app-owned classes activated by the profile's own activation list.

    :param embedded_profile_data: The parsed baked profile.
    """
    reachable_tokens: set[str] = set()
    for member, _, _ in SEP_ADMIN_SETTINGS_CLASSES:
        reachable_tokens.add(member.value)
    for member, _, _ in INVENTORY_ADMIN_SETTINGS_CLASSES:
        reachable_tokens.add(member.value)
    for member, _, _ in TASKS_ADMIN_SETTINGS_CLASSES:
        reachable_tokens.add(member.value)

    profile_apps = SEPSettings().APPS
    for entry in collect_app_owned_settings_classes(profile_apps):
        reachable_tokens.add(entry.setting_class.value)

    allowlist = read_allowlist(embedded_profile_data)
    for key in allowlist:
        class_token = key.split(".")[0]
        assert class_token in reachable_tokens, (
            f"Allowlist entry {key!r} names class {class_token!r} which is not "
            f"reachable in any service under the embedded profile"
        )
