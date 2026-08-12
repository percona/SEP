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
"""Verify the side-car entrypoint's deployment-input expansion."""

import os
import re
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from app.core.auth.config import AuthSettings
from app.core.config import Settings
from app.inventory.config import InventorySettings
from app.sep.config import SEPSettings
from app.tasks.config import TasksSettings
from tests.sidecar.conftest import SETTINGS_ENV_HELPER, SIDECAR_DIR

SUPERVISORD_EXPANSION = re.compile(r"%\(ENV_([A-Za-z0-9_]+)\)s")
UNCONDITIONAL_EXPORT = re.compile(r"^export ([A-Z_][A-Z0-9_]*)=", re.MULTILINE)
BLANK_CLEARED_NAMES_ARRAY = re.compile(
    r"blank_cleared_names=\(\s*(.*?)\s*\)", re.DOTALL
)

CALLER_SHELL_OPTIONS = "set -o errexit -o nounset -o pipefail"
"""The options ``entrypoint.sh`` has active when it sources the helper."""

SHELL_LOCAL_NAMES = frozenset({"PATH", "PWD", "SHLVL", "_"})

DATABASE_PREFIXES = ("SEP", "INVENTORY", "TASKS")

BLANK_BEAT_URI = {"CELERY__BEAT_DBURI": ""}
"""A blank inherited beat URI, the shape the helper has to clear."""


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


def write_secrets(tmp_path: Path, **files: str) -> str:
    """Write the named secret files and return the directory to mount.

    :param tmp_path: The per-test temporary directory.
    :param files: Each canonical name a file supplies, mapped to its contents.
    :return: The directory ``SECRETS_DIR`` should name.
    """
    directory = tmp_path / "secrets"
    directory.mkdir(exist_ok=True)
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")
    return str(directory)


def managed_canonical_names() -> frozenset[str]:
    """Return the canonical names the script's ``blank_cleared_names`` loop manages.

    Parsed from the script rather than duplicated as a literal, so it can
    never drift from the list :func:`apply_environment` relies on to isolate
    a test from whatever one of these names the pytest process itself
    happened to inherit.

    :return: The managed canonical names.
    """
    match = BLANK_CLEARED_NAMES_ARRAY.search(
        SETTINGS_ENV_HELPER.read_text(encoding="utf-8")
    )
    assert match, "blank_cleared_names array not found in settings-env.sh"
    return frozenset(match.group(1).split())


def apply_environment(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]
) -> None:
    """Replay a subprocess's exported environment onto the pytest process.

    A managed name the subprocess left unexported is meant to fall through to
    a mounted file or the baked default -- but the pytest process is not
    otherwise isolated from its own ambient environment, so a managed name
    already set there (from the shell a developer or CI job runs pytest in)
    would outrank both. Every managed name is cleared first so replaying the
    export is the only source left.

    :param monkeypatch: The environment patcher.
    :param environment: The subprocess's exported environment, from :func:`exported`.
    """
    for name in managed_canonical_names():
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        if name not in SHELL_LOCAL_NAMES:
            monkeypatch.setenv(name, value)


@pytest.mark.parametrize("secret_key", [{}, {"SECRET_KEY": ""}], ids=["unset", "empty"])
def test_missing_secret_key_aborts_with_an_actionable_message(
    secret_key: dict[str, str],
):
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
    """Assert one input fans out to the three services and nowhere else."""
    environment = exported(source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="pw"))

    assert [
        environment[f"{prefix}__DATABASE__PASSWORD"] for prefix in DATABASE_PREFIXES
    ] == [
        "pw",
        "pw",
        "pw",
    ]
    assert "CELERY__BEAT_DBURI" not in environment


def test_explicit_canonical_variable_outranks_the_derived_one():
    """Keep the value an operator sets directly on one service."""
    environment = exported(
        source_helper(SECRET_KEY="k", SEP_DB_HOST="a", TASKS__DATABASE__HOST="b")
    )

    assert environment["TASKS__DATABASE__HOST"] == "b"
    assert environment["SEP__DATABASE__HOST"] == "a"


def test_an_inherited_beat_uri_is_neither_read_nor_rewritten():
    """Leave an explicit beat store exactly as it arrived, credentials included.

    The script no longer derives the URI, so the only guarantee it still owes is
    that supplying one changes nothing else about the environment it exports.
    """
    beat_uri = "postgresql://x:secret@y/z"
    baseline = exported(source_helper(SECRET_KEY="k"))

    environment = exported(source_helper(SECRET_KEY="k", CELERY__BEAT_DBURI=beat_uri))

    assert environment["CELERY__BEAT_DBURI"] == beat_uri
    assert {
        name: value
        for name, value in environment.items()
        if name != "CELERY__BEAT_DBURI"
    } == baseline


def test_neither_a_beat_store_nor_a_password_is_exported_by_default():
    """Omit both the beat store and the password, leaving the settings to resolve."""
    environment = exported(source_helper(SECRET_KEY="k"))

    assert "CELERY__BEAT_DBURI" not in environment
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


@pytest.mark.parametrize(
    "endpoint", ["https://h:1", "https://h:1/"], ids=["bare", "trailing-slash"]
)
def test_pmm_endpoint_reaches_the_client_and_the_grafana_provider(endpoint: str):
    """Append PMM's ``/graph`` prefix, trimming a trailing slash that would double it."""
    environment = exported(source_helper(SECRET_KEY="k", SEP_PMM_ENDPOINT=endpoint))

    assert environment["PMM__ENDPOINT"] == "https://h:1"
    assert environment["AUTH__PROVIDER__GRAFANA__ENDPOINT"] == "https://h:1/graph"


def test_nomad_endpoint_is_forwarded_verbatim():
    """Forward the Nomad endpoint verbatim, since its credentials live in the URL."""
    endpoint = "https://a:b@h/nomad"

    environment = exported(source_helper(SECRET_KEY="k", SEP_NOMAD_ENDPOINT=endpoint))

    assert environment["TASKS__NOMAD__ENDPOINT"] == endpoint


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_derived_environment_resolves_against_the_baked_profile(
    monkeypatch: pytest.MonkeyPatch,
):
    """Assert the shell contract and the settings contract agree at their seam."""
    environment = exported(source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="pw"))
    for name, value in environment.items():
        if name not in SHELL_LOCAL_NAMES:
            monkeypatch.setenv(name, value)

    assert "CELERY__BEAT_DBURI" not in environment
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


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_reserved_character_password_reaches_a_usable_service_dsn(
    monkeypatch: pytest.MonkeyPatch,
):
    """Assert the raw password each service receives still yields a parseable DSN.

    The helper exports the password raw, so the encoding the beat URI gets from
    the shell says nothing about the DSN the settings classes build from it.
    """
    password = "p@ss:w/rd"
    environment = exported(source_helper(SECRET_KEY="k", SEP_DB_PASSWORD=password))
    for name, value in environment.items():
        if name not in SHELL_LOCAL_NAMES:
            monkeypatch.setenv(name, value)

    assert [
        unquote(urlsplit(settings_class().DATABASE.URL).password)
        for settings_class in (SEPSettings, InventorySettings, TasksSettings)
    ] == [password, password, password]


def test_secret_key_from_a_file_starts_the_script_without_exporting_it(tmp_path: Path):
    """Clear the gate from a mounted key, leaving each process to read the file."""
    secrets_dir = write_secrets(tmp_path, SECRET_KEY="from-file")

    environment = exported(source_helper(SECRETS_DIR=secrets_dir))

    assert "SECRET_KEY" not in environment


def test_the_missing_key_message_names_the_file_channel(tmp_path: Path):
    """Name both ways of supplying the key when neither is in place."""
    secrets_dir = write_secrets(tmp_path)

    result = source_helper(SECRETS_DIR=secrets_dir)

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr
    assert "openssl rand -hex 32" in result.stderr
    assert "SECRETS_DIR" in result.stderr


@pytest.mark.parametrize("contents", ["", "\n  \n"], ids=["empty", "whitespace-only"])
def test_a_blank_secret_key_file_does_not_satisfy_the_gate(
    tmp_path: Path, contents: str
):
    """Fail fast on a key file that strips to nothing.

    The settings classes reject an empty key outright, so admitting one here
    trades this gate's single actionable line for five crashing children.
    """
    secrets_dir = write_secrets(tmp_path, SECRET_KEY=contents)

    result = source_helper(SECRETS_DIR=secrets_dir)

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_a_blank_secret_key_variable_does_not_shadow_the_file(tmp_path: Path):
    """Clear a blank inherited key, which every child would read over the file."""
    secrets_dir = write_secrets(tmp_path, SECRET_KEY="from-file")

    environment = exported(source_helper(SECRET_KEY="", SECRETS_DIR=secrets_dir))

    assert "SECRET_KEY" not in environment


def test_a_blank_variable_does_not_shadow_the_file_it_defers_to(tmp_path: Path):
    """Clear a blank inherited name, which pydantic would rank above the file."""
    secrets_dir = write_secrets(tmp_path, SEP__DATABASE__PASSWORD="from-file")

    environment = exported(
        source_helper(
            SECRET_KEY="k",
            SEP_DB_PASSWORD="pw",
            SECRETS_DIR=secrets_dir,
            SEP__DATABASE__PASSWORD="",
        )
    )

    assert "SEP__DATABASE__PASSWORD" not in environment


@pytest.mark.parametrize(
    "mount",
    [{"CELERY__BEAT_DBURI": "postgresql://mounted@host:5432/beat"}, {}],
    ids=["mounted", "unmounted"],
)
def test_a_blank_beat_uri_is_cleared(tmp_path: Path, mount: dict[str, str]):
    """Clear a blank inherited beat URI, which outranks every source below it.

    An empty string counts as supplied on the environment side, so leaving it in
    place ranks it above both a mounted file and the derived default, and an empty
    URL fails settings validation rather than falling through to either.
    """
    secrets_dir = write_secrets(tmp_path, **mount)

    environment = exported(
        source_helper(SECRET_KEY="k", SECRETS_DIR=secrets_dir, **BLANK_BEAT_URI)
    )

    assert "CELERY__BEAT_DBURI" not in environment


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_a_blank_beat_uri_still_resolves_the_derived_store(
    monkeypatch: pytest.MonkeyPatch,
):
    """Assert a blank inherited beat URI leaves the derived store reachable.

    Uncleared, the empty string reaches the settings classes and fails URL
    validation, taking every supervisord child down with it.
    """
    environment = exported(
        source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="pw", **BLANK_BEAT_URI)
    )
    for name, value in environment.items():
        if name not in SHELL_LOCAL_NAMES:
            monkeypatch.setenv(name, value)

    assert (
        Settings().CELERY.beat_dburi
        == "postgresql+psycopg2://sep:pw@pmm-server:5432/sep"
    )


def test_a_mounted_canonical_name_is_left_unexported(tmp_path: Path):
    """Suppress only the derived export the file supplies, leaving its siblings."""
    secrets_dir = write_secrets(tmp_path, TASKS__DATABASE__PASSWORD="from-file")

    environment = exported(
        source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="pw", SECRETS_DIR=secrets_dir)
    )

    assert "TASKS__DATABASE__PASSWORD" not in environment
    assert environment["SEP__DATABASE__PASSWORD"] == "pw"
    assert environment["INVENTORY__DATABASE__PASSWORD"] == "pw"


def test_an_explicit_variable_outranks_the_file_and_the_derived_value(tmp_path: Path):
    """Keep an operator's own variable ahead of both lower levels.

    The seed is skipped too, so the wait loops follow the value in force rather
    than the shadowed file.
    """
    secrets_dir = write_secrets(tmp_path, SEP__DATABASE__HOST="from-file")

    environment = exported(
        source_helper(
            SECRET_KEY="k",
            SEP__DATABASE__HOST="from-env",
            SEP_DB_HOST="from-raw",
            SECRETS_DIR=secrets_dir,
        )
    )

    assert environment["SEP__DATABASE__HOST"] == "from-env"
    assert environment["SEP_DB_HOST"] == "from-raw"


def test_mounted_host_and_port_seed_the_supervisord_wait_loops(tmp_path: Path):
    """Point the migrate wait loops at the database the services connect to."""
    secrets_dir = write_secrets(
        tmp_path, SEP__DATABASE__HOST="db.internal", SEP__DATABASE__PORT="6543"
    )

    environment = exported(source_helper(SECRET_KEY="k", SECRETS_DIR=secrets_dir))

    assert environment["SEP_DB_HOST"] == "db.internal"
    assert environment["SEP_DB_PORT"] == "6543"
    assert "SEP__DATABASE__HOST" not in environment
    assert "SEP__DATABASE__PORT" not in environment
    assert environment["INVENTORY__DATABASE__HOST"] == "db.internal"
    assert environment["TASKS__DATABASE__PORT"] == "6543"


def test_a_mounted_password_never_reaches_the_environment(tmp_path: Path):
    """Leave a mounted password in its file, with no derived URI carrying it out.

    This is the whole point of the mount: celery-beat reads the same file through
    the settings classes, so nothing has to put the password back in the
    environment to reach it.
    """
    secrets_dir = write_secrets(tmp_path, SEP__DATABASE__PASSWORD="p@ss:w/rd")

    environment = exported(source_helper(SECRET_KEY="k", SECRETS_DIR=secrets_dir))

    assert "SEP__DATABASE__PASSWORD" not in environment
    assert "CELERY__BEAT_DBURI" not in environment


def test_a_mounted_password_supplies_only_the_name_it_is_named_for(tmp_path: Path):
    """Leave the sibling services unsupplied, since only the raw input fans out.

    This is why the documented mount recipe names all three password files.
    """
    secrets_dir = write_secrets(tmp_path, SEP__DATABASE__PASSWORD="from-file")

    environment = exported(source_helper(SECRET_KEY="k", SECRETS_DIR=secrets_dir))

    assert "INVENTORY__DATABASE__PASSWORD" not in environment
    assert "TASKS__DATABASE__PASSWORD" not in environment


def test_a_file_value_is_stripped(tmp_path: Path):
    """Strip a file the way the settings classes strip it, so both read one value."""
    secrets_dir = write_secrets(tmp_path, SEP__DATABASE__HOST="  padded  \n")

    environment = exported(source_helper(SECRET_KEY="k", SECRETS_DIR=secrets_dir))

    assert environment["SEP_DB_HOST"] == "padded"
    assert environment["INVENTORY__DATABASE__HOST"] == "padded"


def test_an_empty_file_counts_as_a_supplied_value(tmp_path: Path):
    """Treat a blank mount as supplied, which is how the settings classes read it."""
    secrets_dir = write_secrets(tmp_path, SEP__DATABASE__PASSWORD="")

    environment = exported(
        source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="pw", SECRETS_DIR=secrets_dir)
    )

    assert "SEP__DATABASE__PASSWORD" not in environment
    assert environment["INVENTORY__DATABASE__PASSWORD"] == "pw"
    assert environment["TASKS__DATABASE__PASSWORD"] == "pw"


def test_a_symlink_escaping_the_directory_does_not_supply_a_name(tmp_path: Path):
    """Ignore an escaping symlink, so the export the settings classes need survives."""
    outside = tmp_path / "outside"
    outside.write_text("escaped-value", encoding="utf-8")
    secrets_dir = write_secrets(tmp_path)
    (Path(secrets_dir) / "SEP__DATABASE__HOST").symlink_to(outside)

    environment = exported(source_helper(SECRET_KEY="k", SECRETS_DIR=secrets_dir))

    assert environment["SEP__DATABASE__HOST"] == "pmm-server"
    assert environment["SEP_DB_HOST"] == "pmm-server"


def test_a_symlink_escaping_the_directory_does_not_satisfy_the_gate(tmp_path: Path):
    """Reject an escaping key file, which no settings class would read either."""
    outside = tmp_path / "outside"
    outside.write_text("escaped-value", encoding="utf-8")
    secrets_dir = write_secrets(tmp_path)
    (Path(secrets_dir) / "SECRET_KEY").symlink_to(outside)

    result = source_helper(SECRETS_DIR=secrets_dir)

    assert result.returncode != 0


def test_a_kubernetes_projected_secret_is_supplied(tmp_path: Path):
    """Resolve the ``..data`` layout Kubernetes projects, which stays inside."""
    secrets_dir = Path(write_secrets(tmp_path))
    revision = secrets_dir / "..2026_01_01"
    revision.mkdir()
    (revision / "SECRET_KEY").write_text("projected-value", encoding="utf-8")
    (secrets_dir / "..data").symlink_to("..2026_01_01")
    (secrets_dir / "SECRET_KEY").symlink_to("..data/SECRET_KEY")

    environment = exported(source_helper(SECRETS_DIR=str(secrets_dir)))

    assert "SECRET_KEY" not in environment


def test_a_lowercase_file_name_supplies_the_canonical_name(tmp_path: Path):
    """Match file names case-insensitively, as the settings source matches them.

    An exact-match lookup would export the derived value instead, and an
    exported name outranks every secret file.
    """
    secrets_dir = write_secrets(tmp_path, sep__database__password="from-file")

    environment = exported(
        source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="raw", SECRETS_DIR=secrets_dir)
    )

    assert "SEP__DATABASE__PASSWORD" not in environment
    assert environment["INVENTORY__DATABASE__PASSWORD"] == "raw"
    assert environment["TASKS__DATABASE__PASSWORD"] == "raw"


def test_a_lowercase_secret_key_file_satisfies_the_gate(tmp_path: Path):
    """Clear the gate from a lowercased key file, which the settings classes read."""
    secrets_dir = write_secrets(tmp_path, secret_key="from-file")

    environment = exported(source_helper(SECRETS_DIR=secrets_dir))

    assert "SECRET_KEY" not in environment


def test_a_secret_in_a_subdirectory_does_not_supply_a_name(tmp_path: Path):
    """Ignore a nested secret, whose settings-side key can match no field."""
    secrets_dir = Path(write_secrets(tmp_path))
    nested = secrets_dir / "sub"
    nested.mkdir()
    (nested / "SEP__DATABASE__HOST").write_text("nested-value", encoding="utf-8")

    environment = exported(source_helper(SECRET_KEY="k", SECRETS_DIR=str(secrets_dir)))

    assert environment["SEP__DATABASE__HOST"] == "pmm-server"


@pytest.mark.parametrize(
    "build_secrets_dir",
    [
        lambda tmp_path: str(tmp_path / "missing"),
        write_secrets,
        lambda tmp_path: write_secrets(tmp_path, UNRELATED="value"),
    ],
    ids=["absent", "empty", "unrelated-file"],
)
def test_an_unusable_secrets_directory_changes_nothing(
    tmp_path: Path, build_secrets_dir: Callable[[Path], str]
):
    """Leave today's exported environment untouched when no file matches a name."""
    secrets_dir = build_secrets_dir(tmp_path)
    baseline = exported(source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="pw"))

    environment = exported(
        source_helper(SECRET_KEY="k", SEP_DB_PASSWORD="pw", SECRETS_DIR=secrets_dir)
    )

    assert {
        name: value for name, value in environment.items() if name != "SECRETS_DIR"
    } == baseline


@pytest.mark.usefixtures("embedded_profile_cwd")
def test_a_mounted_secret_resolves_through_the_shell_into_the_settings_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Assert the shell's suppression and the settings classes' file read compose."""
    password = "p@ss:w/rd"
    secrets_dir = write_secrets(
        tmp_path, SECRET_KEY="from-file", SEP__DATABASE__PASSWORD=password
    )
    environment = exported(source_helper(SECRETS_DIR=secrets_dir))
    for name in ("SECRET_KEY", "SEP__DATABASE__PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        if name not in SHELL_LOCAL_NAMES:
            monkeypatch.setenv(name, value)

    assert not [name for name in environment if "PASSWORD" in name]
    assert "CELERY__BEAT_DBURI" not in environment
    assert (
        Settings(_secrets_dir=secrets_dir).SECRET_KEY.get_secret_value() == "from-file"
    )
    assert (
        SEPSettings(_secrets_dir=secrets_dir).DATABASE.PASSWORD.get_secret_value()
        == password
    )
    assert (
        Settings(_secrets_dir=secrets_dir).CELERY.beat_dburi
        == "postgresql+psycopg2://sep:p%40ss%3Aw%2Frd@pmm-server:5432/sep"
    )


class TestBlankNamesWhoseGuardMightNeverFire:
    """Clear a canonical name inherited blank while its ``SEP_*`` guard is inactive.

    ``export_canonical`` only clears a blank when it actually runs, and four
    guards skip calling it whenever their raw input is absent. Two more names
    -- ``SEP_INTERNAL_TOKEN`` and ``BASE_URL`` -- have no guard at all and are
    never touched by the script. All ten have to clear regardless.
    """

    ALL_BLANK_CLEARED_NAMES: tuple[str, ...] = (
        "SEP__DATABASE__PASSWORD",
        "INVENTORY__DATABASE__PASSWORD",
        "TASKS__DATABASE__PASSWORD",
        "AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN",
        "PMM__API_KEY",
        "PMM__ENDPOINT",
        "AUTH__PROVIDER__GRAFANA__ENDPOINT",
        "TASKS__NOMAD__ENDPOINT",
        "SEP_INTERNAL_TOKEN",
        "BASE_URL",
    )

    @pytest.mark.parametrize("canonical_name", ALL_BLANK_CLEARED_NAMES)
    def test_a_blank_name_is_cleared_with_a_file_mounted(
        self, tmp_path: Path, canonical_name: str
    ):
        """Defer to the file even though no guard ever calls ``export_canonical``."""
        secrets_dir = write_secrets(tmp_path, **{canonical_name: "from-file"})

        environment = exported(
            source_helper(
                SECRET_KEY="k", SECRETS_DIR=secrets_dir, **{canonical_name: ""}
            )
        )

        assert canonical_name not in environment

    @pytest.mark.parametrize("canonical_name", ALL_BLANK_CLEARED_NAMES)
    def test_a_blank_name_is_cleared_with_no_file_mounted(self, canonical_name: str):
        """Fall through to the derived value or default, not an exported blank."""
        environment = exported(source_helper(SECRET_KEY="k", **{canonical_name: ""}))

        assert canonical_name not in environment

    @pytest.mark.parametrize("canonical_name", ALL_BLANK_CLEARED_NAMES)
    def test_an_explicit_value_is_untouched_by_the_clear(self, canonical_name: str):
        """Leave a genuinely non-empty inherited value exactly as it arrived."""
        environment = exported(
            source_helper(SECRET_KEY="k", **{canonical_name: "explicit-value"})
        )

        assert environment[canonical_name] == "explicit-value"

    def test_the_scripts_managed_name_list_matches_this_suites_own(self):
        """Keep the two enumerated lists in lockstep.

        Otherwise a name added to one and not the other goes untested or
        unmanaged without either side failing.
        """
        assert managed_canonical_names() == set(self.ALL_BLANK_CLEARED_NAMES) | {
            "CELERY__BEAT_DBURI"
        }

    @pytest.mark.usefixtures("embedded_profile_cwd")
    def test_a_mounted_password_resolves_even_with_its_guard_inactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Assert the file resolves though nothing sets ``SEP_DB_PASSWORD``.

        Before the fix this blank had nothing to clear it: the password guard
        never fires without a raw input, so ``export_canonical`` never runs and
        the file stays shadowed.
        """
        secrets_dir = write_secrets(tmp_path, SEP__DATABASE__PASSWORD="from-file")
        environment = exported(
            source_helper(
                SECRET_KEY="k", SECRETS_DIR=secrets_dir, SEP__DATABASE__PASSWORD=""
            )
        )
        apply_environment(monkeypatch, environment)

        assert (
            SEPSettings(_secrets_dir=secrets_dir).DATABASE.PASSWORD.get_secret_value()
            == "from-file"
        )

    @pytest.mark.usefixtures("embedded_profile_cwd")
    def test_a_mounted_internal_token_resolves_even_with_its_guard_inactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Assert the file resolves though nothing derives ``SEP_INTERNAL_TOKEN``.

        Unlike the URL-typed names, an uncleared blank here would not crash:
        ``derive_internal_token`` treats an empty ``SecretStr`` the same as an
        unset one and silently overwrites it with a value derived from
        ``SECRET_KEY``, discarding the mounted token instead. A shell-level
        "absent from the environment" assertion can't tell that apart from
        this -- the derived fallback also leaves the name unexported.
        """
        secrets_dir = write_secrets(tmp_path, SEP_INTERNAL_TOKEN="from-file")
        environment = exported(
            source_helper(
                SECRET_KEY="k", SECRETS_DIR=secrets_dir, SEP_INTERNAL_TOKEN=""
            )
        )
        apply_environment(monkeypatch, environment)

        assert (
            Settings(_secrets_dir=secrets_dir).SEP_INTERNAL_TOKEN.get_secret_value()
            == "from-file"
        )

    @pytest.mark.usefixtures("embedded_profile_cwd")
    def test_mounted_grafana_credentials_resolve_even_with_their_guard_inactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Assert both files resolve though nothing sets ``SEP_GRAFANA_TOKEN``.

        The token guard never fires without a raw input, so without the
        unconditional clear both files would stay shadowed the same way the
        password file did before the fix.
        """
        secrets_dir = write_secrets(
            tmp_path,
            AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN="from-file",
            PMM__API_KEY="from-file",
        )
        environment = exported(
            source_helper(
                SECRET_KEY="k",
                SECRETS_DIR=secrets_dir,
                AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN="",
                PMM__API_KEY="",
            )
        )
        apply_environment(monkeypatch, environment)

        assert (
            AuthSettings(_secrets_dir=secrets_dir)
            .PROVIDER["grafana"]
            .service_account_token.get_secret_value()
            == "from-file"
        )
        assert (
            Settings(_secrets_dir=secrets_dir).PMM.api_key.get_secret_value()
            == "from-file"
        )

    @pytest.mark.usefixtures("embedded_profile_cwd")
    @pytest.mark.parametrize(
        "mount",
        [{}, {"BASE_URL": "https://mounted:9443/sep"}],
        ids=["falls-through-to-none", "resolves-through-the-file"],
    )
    def test_a_blank_base_url_resolves_through_the_file_or_to_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mount: dict[str, str]
    ):
        """Match a mounted file or the baked ``BASE_URL: null`` default, never an empty URL."""
        secrets_dir = write_secrets(tmp_path, **mount)
        environment = exported(
            source_helper(SECRET_KEY="k", SECRETS_DIR=secrets_dir, BASE_URL="")
        )
        apply_environment(monkeypatch, environment)
        expected = mount.get("BASE_URL")

        base_url = Settings(_secrets_dir=secrets_dir).BASE_URL
        assert (str(base_url) if base_url is not None else base_url) == expected


class TestApplyEnvironmentIsolatesFromTheAmbientProcess:
    """Prove the pre-clear in ``apply_environment`` -- not just the subprocess run -- matters."""

    @pytest.mark.usefixtures("embedded_profile_cwd")
    def test_an_ambient_managed_name_does_not_survive_a_correctly_cleared_export(
        self, monkeypatch: pytest.MonkeyPatch, embedded_profile_data: dict
    ):
        """Assert a name the subprocess correctly left unexported outranks an ambient leak.

        The subprocess's own environment starts clean, so ``PMM__ENDPOINT``
        never reaches it here -- this sets it directly on the pytest process
        first, the way a developer's or CI job's shell might, to prove that
        without ``apply_environment``'s own clear, replaying the export alone
        would leave the leaked value in place.
        """
        monkeypatch.setenv("PMM__ENDPOINT", "https://leaked-from-the-pytest-process")
        environment = exported(source_helper(SECRET_KEY="k", PMM__ENDPOINT=""))
        apply_environment(monkeypatch, environment)

        assert (
            Settings().PMM.endpoint
            == embedded_profile_data["default"]["PMM"]["ENDPOINT"]
        )


class TestGuardInactiveEndpointsResolveWithoutCrashing:
    """Assert a blanked URL-typed name with its guard inactive never crashes.

    ``StrCredentialHttpUrl``/``CredentialHttpUrl`` reject an empty string but
    accept ``None``, so an uncleared blank fails settings validation outright
    -- taking every supervisord child down -- even though the baked profile
    carries a perfectly good default.
    """

    @pytest.mark.usefixtures("embedded_profile_cwd")
    @pytest.mark.parametrize(
        "mount",
        [{}, {"PMM__ENDPOINT": "https://mounted:9443"}],
        ids=["falls-through-to-the-baked-profile", "resolves-through-the-file"],
    )
    def test_pmm_endpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        embedded_profile_data: dict,
        mount: dict[str, str],
    ):
        """Assert a blank ``PMM__ENDPOINT`` never reaches ``PMMSettings`` empty."""
        secrets_dir = write_secrets(tmp_path, **mount)
        environment = exported(
            source_helper(SECRET_KEY="k", SECRETS_DIR=secrets_dir, PMM__ENDPOINT="")
        )
        apply_environment(monkeypatch, environment)
        expected = mount.get(
            "PMM__ENDPOINT", embedded_profile_data["default"]["PMM"]["ENDPOINT"]
        )

        assert Settings(_secrets_dir=secrets_dir).PMM.endpoint == expected

    @pytest.mark.usefixtures("embedded_profile_cwd")
    @pytest.mark.parametrize(
        "mount",
        [{}, {"TASKS__NOMAD__ENDPOINT": "https://mounted:9443/nomad"}],
        ids=["falls-through-to-the-baked-profile", "resolves-through-the-file"],
    )
    def test_nomad_endpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        embedded_profile_data: dict,
        mount: dict[str, str],
    ):
        """Assert a blank ``TASKS__NOMAD__ENDPOINT`` never crashes ``TasksSettings``."""
        secrets_dir = write_secrets(tmp_path, **mount)
        environment = exported(
            source_helper(
                SECRET_KEY="k",
                SEP_DB_PASSWORD="pw",
                SECRETS_DIR=secrets_dir,
                TASKS__NOMAD__ENDPOINT="",
            )
        )
        apply_environment(monkeypatch, environment)
        expected = mount.get(
            "TASKS__NOMAD__ENDPOINT",
            embedded_profile_data["default"]["TASKS"]["NOMAD"]["ENDPOINT"],
        )

        assert str(TasksSettings(_secrets_dir=secrets_dir).NOMAD.endpoint) == expected

    @pytest.mark.usefixtures("embedded_profile_cwd")
    @pytest.mark.parametrize(
        "mount",
        [{}, {"AUTH__PROVIDER__GRAFANA__ENDPOINT": "https://mounted:9443/graph"}],
        ids=["falls-through-to-the-baked-profile", "resolves-through-the-file"],
    )
    def test_grafana_endpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        embedded_profile_data: dict,
        mount: dict[str, str],
    ):
        """Assert a blank Grafana endpoint never crashes ``AuthSettings`` either."""
        secrets_dir = write_secrets(tmp_path, **mount)
        environment = exported(
            source_helper(
                SECRET_KEY="k",
                SECRETS_DIR=secrets_dir,
                AUTH__PROVIDER__GRAFANA__ENDPOINT="",
            )
        )
        apply_environment(monkeypatch, environment)
        expected = mount.get(
            "AUTH__PROVIDER__GRAFANA__ENDPOINT",
            embedded_profile_data["default"]["AUTH"]["PROVIDER"]["grafana"]["endpoint"],
        )

        provider = AuthSettings(_secrets_dir=secrets_dir).PROVIDER["grafana"]
        assert str(provider.endpoint) == expected
