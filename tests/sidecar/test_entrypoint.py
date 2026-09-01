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
"""Cover the side-car PID 1's Grafana mint step and its stale-sentinel clearing."""

import os
import re
import subprocess
from collections.abc import Iterator
from configparser import RawConfigParser
from pathlib import Path

import pytest

from tests.sidecar.conftest import SIDECAR_DIR

ENTRYPOINT = SIDECAR_DIR / "entrypoint.sh"
SETTINGS_ENV_HELPER = SIDECAR_DIR / "settings-env.sh"
SUPERVISORD_CONF = SIDECAR_DIR / "supervisord.conf"
MINT_HELPER_NAME = "grafana_service_account.py"

SENTINEL_PATH = re.compile(r"/tmp/migrate-([a-z]+)\.ok")

CANONICAL_NAMES = (
    "AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN",
    "PMM__API_KEY",
)

MINTED_TOKEN = "glsa_minted_at_container_start"

FAKE_SUPERVISORD = r"""#!/usr/bin/env bash
env -0 > "$FAKE_SUPERVISORD_ENV"
ls -1 /tmp/migrate-*.ok > "$FAKE_SUPERVISORD_SENTINELS" 2> /dev/null || true
"""
"""A stand-in for supervisord recording what its children would inherit.

The sentinel listing is taken here rather than after the run because what the
clearing must guarantee is that no stale marker survives *into* the spawn — an
assertion made once the entrypoint has exited could not tell the two apart.
"""

STUB_MINT_HELPER = """import os
import sys

with open(os.environ["FAKE_HELPER_ARGV"], "w", encoding="utf-8") as handle:
    handle.write("\\n".join(sys.argv))
sys.stdout.write(os.environ["FAKE_HELPER_STDOUT"])
sys.exit(int(os.environ["FAKE_HELPER_EXIT"]))
"""
"""A stand-in for the mint helper, answering whatever the case calls for."""


class FakeContainer:
    """Run the real entrypoint outside an image, with its two exec points stubbed.

    The entrypoint resolves its siblings relative to itself, so a copy of the
    tree is enough to exercise it; ``supervisord`` is shadowed on ``PATH`` and
    the mint helper is replaced in the copied tree.
    """

    def __init__(self, root: Path):
        """Lay the copied application root and the fake runtime out under ``root``.

        :param root: The per-test temporary directory to build in.
        """
        self.app_dir = root / "app"
        self.app_dir.mkdir()
        for source in (ENTRYPOINT, SETTINGS_ENV_HELPER):
            target = self.app_dir / source.name
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            target.chmod(0o755)
        (self.app_dir / MINT_HELPER_NAME).write_text(STUB_MINT_HELPER, encoding="utf-8")

        self._bin = root / "bin"
        self._bin.mkdir()
        supervisord = self._bin / "supervisord"
        supervisord.write_text(FAKE_SUPERVISORD, encoding="utf-8")
        supervisord.chmod(0o755)

        self._environment_file = root / "supervisord-env"
        self._argv_file = root / "helper-argv"
        self._sentinel_file = root / "supervisord-sentinels"

    def start(
        self, *, token: str = MINTED_TOKEN, exit_code: int = 0, **inputs: str
    ) -> subprocess.CompletedProcess[str]:
        """Run the entrypoint with the mint helper answering as configured.

        :param token: What the stub helper prints for the entrypoint to capture.
        :param exit_code: What the stub helper exits with.
        :param inputs: Deployment inputs to place in the environment.
        :return: The completed entrypoint run.
        """
        environment = {
            "PATH": f"{self._bin}{os.pathsep}{os.environ['PATH']}",
            "SECRET_KEY": "k",
            "FAKE_SUPERVISORD_ENV": str(self._environment_file),
            "FAKE_SUPERVISORD_SENTINELS": str(self._sentinel_file),
            "FAKE_HELPER_ARGV": str(self._argv_file),
            "FAKE_HELPER_STDOUT": token,
            "FAKE_HELPER_EXIT": str(exit_code),
            **inputs,
        }
        return subprocess.run(
            [str(self.app_dir / ENTRYPOINT.name)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    @property
    def supervised_environment(self) -> dict[str, str]:
        """Return the environment supervisord was handed.

        :return: The exported variables.
        """
        recorded = self._environment_file.read_text(encoding="utf-8")
        return dict(
            entry.split("=", 1) for entry in recorded.split("\0") if "=" in entry
        )

    @property
    def sentinels_at_spawn(self) -> list[str]:
        """Return the schema sentinels present when supervisord was reached.

        :return: One path per surviving sentinel, empty when the clear worked.
        """
        return self._sentinel_file.read_text(encoding="utf-8").split()

    @property
    def helper_argv(self) -> list[str]:
        """Return the argv the entrypoint invoked the mint helper with.

        :return: One entry per argument, in order.
        """
        return self._argv_file.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def container(tmp_path: Path) -> FakeContainer:
    """Return a fake container ready to run the entrypoint.

    :param tmp_path: The per-test temporary directory.
    :return: The fake container.
    """
    return FakeContainer(tmp_path)


def test_a_minted_token_reaches_both_canonical_names(container: FakeContainer):
    """Hand the minted token to every supervised program, through one function."""
    result = container.start()

    assert result.returncode == 0, result.stderr
    for name in CANONICAL_NAMES:
        assert container.supervised_environment[name] == MINTED_TOKEN


def test_a_helper_resolving_nothing_leaves_the_names_alone(container: FakeContainer):
    """Leave the baked empty token standing when the pre-flight resolves nothing."""
    result = container.start(token="")

    assert result.returncode == 0, result.stderr
    for name in CANONICAL_NAMES:
        assert name not in container.supervised_environment


def test_a_failing_helper_does_not_take_the_container_down(container: FakeContainer):
    """Degrade auth exactly as it degrades today rather than killing PID 1.

    The entrypoint runs under ``errexit``, so without the failure being absorbed
    the helper's non-zero exit would end PID 1 before supervisord ever starts.
    """
    result = container.start(token="", exit_code=1)

    assert result.returncode == 0, result.stderr
    assert container.supervised_environment
    for name in CANONICAL_NAMES:
        assert name not in container.supervised_environment


def test_an_explicit_token_still_outranks_the_mint(container: FakeContainer):
    """Keep the operator's own value, which the pre-flight resolves beneath."""
    container.start(SEP_GRAFANA_TOKEN="glsa_explicit")

    for name in CANONICAL_NAMES:
        assert container.supervised_environment[name] == "glsa_explicit"


def test_the_token_never_enters_the_helpers_argv(container: FakeContainer):
    """Keep the credential out of ``/proc``, which every process in the namespace reads."""
    container.start()

    assert container.helper_argv == [str(container.app_dir / MINT_HELPER_NAME)]


def test_the_grafana_admin_credential_stops_at_the_mint(container: FakeContainer):
    """Keep the admin pair out of every supervised program's environment.

    It is more privileged than the token it mints, and only the mint step reads
    it, so it must not outlive that step.
    """
    container.start(GF_SECURITY_ADMIN_USER="root", GF_SECURITY_ADMIN_PASSWORD="s3cret")

    supervised = container.supervised_environment
    assert "GF_SECURITY_ADMIN_USER" not in supervised
    assert "GF_SECURITY_ADMIN_PASSWORD" not in supervised


def cleared_sentinels() -> set[str]:
    """Return the schema steps whose sentinel the entrypoint clears.

    :return: One bare step name per cleared sentinel path.
    """
    return set(SENTINEL_PATH.findall(ENTRYPOINT.read_text(encoding="utf-8")))


def one_shot_programs() -> set[str]:
    """Return the schema steps supervisord runs as one-shots.

    :return: One bare step name per ``migrate-*`` program.
    """
    parser = RawConfigParser()
    parser.read_string(SUPERVISORD_CONF.read_text(encoding="utf-8"))
    return {
        section.split(":", 1)[1].removeprefix("migrate-")
        for section in parser.sections()
        if section.startswith("program:migrate-")
    }


@pytest.fixture
def owned_sentinels() -> Iterator[set[str]]:
    """Return the sentinel paths this suite owns, removing them afterwards.

    The paths are hardcoded across the entrypoint, the program table and the
    healthcheck alike, so these tests act on the real ``/tmp`` ones rather than
    introducing a directory knob that would exist only for them. Cleaning up
    keeps a failed run from leaving markers behind.

    :return: One absolute sentinel path per schema step.
    """
    paths = {f"/tmp/migrate-{step}.ok" for step in one_shot_programs()}
    yield paths
    for path in paths:
        Path(path).unlink(missing_ok=True)


def test_stale_sentinels_are_cleared_before_supervisord(
    container: FakeContainer, owned_sentinels: set[str]
):
    """Clear a previous run's sentinels from PID 1, before any program is spawned.

    ``/tmp`` survives a container restart and each one-shot clears its own
    sentinel only *after* being spawned — concurrently with the apps now gated on
    it — so a gate could otherwise read a previous run's marker and release an app
    against a schema this run has not re-applied.

    Only this suite's own sentinels are asserted on. The recording stub globs all
    of ``/tmp``, and a sibling test holding an unrelated ``migrate-*.ok`` would
    otherwise fail this one under the suite's parallel runner.
    """
    for path in owned_sentinels:
        Path(path).touch()

    result = container.start()

    assert result.returncode == 0, result.stderr
    assert set(container.sentinels_at_spawn) & owned_sentinels == set()


def test_clearing_is_not_fatal_when_no_sentinel_exists(
    container: FakeContainer, owned_sentinels: set[str]
):
    """Start supervisord on a first boot, where there is nothing to clear.

    The entrypoint runs under ``errexit``, so a clear that failed on an unmatched
    name would kill PID 1 instead of starting the container.
    """
    for path in owned_sentinels:
        Path(path).unlink(missing_ok=True)

    result = container.start()

    assert result.returncode == 0, result.stderr
    assert container.supervised_environment


def test_every_one_shot_sentinel_is_cleared():
    """Assert the cleared names are exactly the one-shots supervisord runs.

    The entrypoint names them rather than globbing, so this is what keeps the two
    files from drifting: a schema step added to the program table without being
    cleared here would survive a restart and release the gate on a stale marker.
    """
    assert cleared_sentinels() == one_shot_programs()
