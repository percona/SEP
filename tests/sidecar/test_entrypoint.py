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
"""Cover the side-car PID 1's Grafana mint step."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.sidecar.conftest import SIDECAR_DIR

ENTRYPOINT = SIDECAR_DIR / "entrypoint.sh"
SETTINGS_ENV_HELPER = SIDECAR_DIR / "settings-env.sh"
MINT_HELPER_NAME = "grafana_service_account.py"

CANONICAL_NAMES = (
    "AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN",
    "PMM__API_KEY",
)

MINTED_TOKEN = "glsa_minted_at_container_start"

FAKE_SUPERVISORD = r"""#!/usr/bin/env bash
env -0 > "$FAKE_SUPERVISORD_ENV"
"""
"""A stand-in for supervisord recording the environment its children inherit."""

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
