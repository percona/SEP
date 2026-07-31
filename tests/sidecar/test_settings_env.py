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
"""Tests for the side-car entrypoint's deployment-input expansion."""

import os
import re
import shlex
import subprocess

import pytest

from app.core.auth.config import AuthSettings
from app.core.config import Settings
from app.inventory.config import InventorySettings
from app.sep.config import SEPSettings
from app.tasks.config import TasksSettings
from tests.sidecar.conftest import SETTINGS_ENV_HELPER, SIDECAR_DIR

SUPERVISORD_EXPANSION = re.compile(r"%\(ENV_([A-Za-z0-9_]+)\)s")
UNCONDITIONAL_EXPORT = re.compile(r"^export ([A-Z_][A-Z0-9_]*)=", re.MULTILINE)

CALLER_SHELL_OPTIONS = "set -o errexit -o nounset -o pipefail"
"""The options ``entrypoint.sh`` has active when it sources the helper."""

SHELL_LOCAL_NAMES = frozenset({"PATH", "PWD", "SHLVL", "_"})

DATABASE_PREFIXES = ("SEP", "INVENTORY", "TASKS")


def source_helper(**inputs: str) -> subprocess.CompletedProcess[str]:
    """Run the helper from an otherwise empty environment.

    :param inputs: The deployment inputs to place in the environment.
    :return: The completed ``bash`` run, whose stdout is a NUL-delimited ``env``.
    """
    script = (
        f"{CALLER_SHELL_OPTIONS}\n. {shlex.quote(str(SETTINGS_ENV_HELPER))}\nenv -0"
    )
    return subprocess.run(
        ["bash", "-c", script],
        env={"PATH": os.environ["PATH"], **inputs},
        capture_output=True,
        text=True,
        check=False,
    )


def exported(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    """Return the environment the helper exported.

    :param result: A completed :func:`source_helper` run.
    :return: The exported variables.
    """
    assert result.returncode == 0, result.stderr
    return dict(
        entry.split("=", 1) for entry in result.stdout.split("\0") if "=" in entry
    )


@pytest.mark.parametrize("secret_key", [{}, {"SECRET_KEY": ""}], ids=["unset", "empty"])
def test_missing_secret_key_aborts_with_an_actionable_message(secret_key):
    """Reject a missing key, which each supervisord child would resolve differently."""
    result = source_helper(**secret_key)

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr
    assert "openssl rand -hex 32" in result.stderr


def test_database_host_and_port_defaults_are_exported():
    """Assert the host and port defaults reach supervisord's own environment.

    ``%(ENV_...)s`` expands from there, so a bare assignment would leave the
    migration wait loops pointing at undefined names.
    """
    environment = exported(source_helper(SECRET_KEY="k"))

    assert environment["SEP_DB_HOST"] == "pmm-server"
    assert environment["SEP_DB_PORT"] == "5432"
    assert all(
        environment[f"{prefix}__DATABASE__{field}"]
        for prefix in DATABASE_PREFIXES
        for field in ("HOST", "PORT")
    )


def test_supervisord_expansions_are_exported_unconditionally():
    """Assert every name supervisord expands is exported outside a conditional.

    An undefined ``%(ENV_...)s`` name aborts supervisord rather than starting it.
    """
    expansions = set(
        SUPERVISORD_EXPANSION.findall(
            (SIDECAR_DIR / "supervisord.conf").read_text(encoding="utf-8")
        )
    )

    assert expansions
    assert expansions <= set(
        UNCONDITIONAL_EXPORT.findall(SETTINGS_ENV_HELPER.read_text(encoding="utf-8"))
    )


def test_password_reaches_every_canonical_destination():
    """Assert one input fans out to the three services and the beat store."""
    environment = exported(source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="pw"))

    assert [
        environment[f"{prefix}__DATABASE__PASSWORD"] for prefix in DATABASE_PREFIXES
    ] == [
        "pw",
        "pw",
        "pw",
    ]
    assert (
        environment["CELERY__BEAT_DBURI"] == "postgresql://sep:pw@pmm-server:5432/sep"
    )


def test_password_is_percent_encoded_into_the_beat_uri():
    """Encode a password containing URI syntax, which would corrupt the authority."""
    environment = exported(source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="p@ss:w/rd"))

    assert (
        environment["CELERY__BEAT_DBURI"]
        == "postgresql://sep:p%40ss%3Aw%2Frd@pmm-server:5432/sep"
    )
    assert environment["SEP__DATABASE__PASSWORD"] == "p@ss:w/rd"


def test_explicit_canonical_variable_outranks_the_derived_one():
    """Keep the value an operator sets directly on one service."""
    environment = exported(
        source_helper(SECRET_KEY="k", SEP_DB_HOST="a", TASKS__DATABASE__HOST="b")
    )

    assert environment["TASKS__DATABASE__HOST"] == "b"
    assert environment["SEP__DATABASE__HOST"] == "a"


def test_explicit_beat_uri_is_left_untouched():
    """Keep an explicit beat store, which may point away from the service database."""
    environment = exported(
        source_helper(SECRET_KEY="k", CELERY__BEAT_DBURI="postgresql://x@y/z")
    )

    assert environment["CELERY__BEAT_DBURI"] == "postgresql://x@y/z"


def test_beat_uri_is_derived_without_a_password():
    """Derive the beat store from the host/port input when no password is set."""
    environment = exported(source_helper(SECRET_KEY="k"))

    assert environment["CELERY__BEAT_DBURI"] == "postgresql://sep@pmm-server:5432/sep"
    assert not [name for name in environment if name.endswith("__DATABASE__PASSWORD")]


def test_grafana_token_reaches_the_provider_and_the_pmm_client():
    """Assert one minted token serves both Grafana sign-in and the PMM syncer."""
    environment = exported(source_helper(SECRET_KEY="k", SEP_GRAFANA_TOKEN="glsa_x"))

    assert environment["AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN"] == "glsa_x"
    assert environment["PMM__API_KEY"] == "glsa_x"


def test_no_grafana_variables_without_a_token():
    """Leave the profile's empty token standing when no token is supplied."""
    environment = exported(source_helper(SECRET_KEY="k"))

    assert "AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN" not in environment
    assert "PMM__API_KEY" not in environment


def test_pmm_endpoint_reaches_the_client_and_the_grafana_provider():
    """Append PMM's ``/graph`` prefix for the Grafana provider's endpoint."""
    environment = exported(
        source_helper(SECRET_KEY="k", SEP_PMM_ENDPOINT="https://h:1")
    )

    assert environment["PMM__ENDPOINT"] == "https://h:1"
    assert environment["AUTH__PROVIDER__GRAFANA__ENDPOINT"] == "https://h:1/graph"


def test_pmm_endpoint_trailing_slash_does_not_double():
    """Trim a trailing slash before appending the Grafana provider's prefix."""
    environment = exported(
        source_helper(SECRET_KEY="k", SEP_PMM_ENDPOINT="https://h:1/")
    )

    assert environment["PMM__ENDPOINT"] == "https://h:1"
    assert environment["AUTH__PROVIDER__GRAFANA__ENDPOINT"] == "https://h:1/graph"


def test_nomad_endpoint_is_forwarded_verbatim():
    """Forward the Nomad endpoint verbatim, since its credentials live in the URL."""
    endpoint = "https://a:b@h/nomad"

    environment = exported(source_helper(SECRET_KEY="k", SEP_NOMAD_ENDPOINT=endpoint))

    assert environment["TASKS__NOMAD__ENDPOINT"] == endpoint


def test_derived_environment_resolves_against_the_baked_profile(
    embedded_profile_cwd, monkeypatch: pytest.MonkeyPatch
):
    """Assert the shell contract and the settings contract agree at their seam."""
    environment = exported(source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="pw"))
    for name, value in environment.items():
        if name not in SHELL_LOCAL_NAMES:
            monkeypatch.setenv(name, value)

    assert (
        Settings().CELERY.beat_dburi
        == "postgresql+psycopg2://sep:pw@pmm-server:5432/sep"
    )
    assert (
        AuthSettings().PROVIDER["grafana"].service_account_token.get_secret_value()
        == ""
    )
    assert [
        settings_class().DATABASE.PASSWORD.get_secret_value()
        for settings_class in (SEPSettings, InventorySettings, TasksSettings)
    ] == ["pw", "pw", "pw"]
