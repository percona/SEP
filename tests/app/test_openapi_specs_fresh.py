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

"""Guard the committed frontend OpenAPI spec fixtures and the dump's settings pins."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DUMP_SCRIPT = REPO_ROOT / "scripts" / "dump_openapi.py"


def test_committed_openapi_specs_are_fresh():
    """Assert the committed whole-app specs match a fresh ``.openapi()`` dump.

    Runs ``scripts/dump_openapi.py --check`` in a subprocess so the imported
    app objects carry no conftest-injected routers, then asserts the committed
    ``frontend/packages/api/specs/*.json`` fixtures the frontend codegen
    consumes have not drifted from the live backend contract.
    """
    result = subprocess.run(
        [sys.executable, str(DUMP_SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_dump_script_ignores_developer_auth_config(tmp_path):
    """Assert the dump pins the canonical provider over a local auth configuration.

    A checkout configured for a non-Casdoor provider names it in the dotenv file
    ``ENV_FILE`` points at, and the dotenv settings source reads that file from
    disk, so clearing the environment alone leaves the provider in place. Point
    the subprocess at such a file *and* export a provider variable, so the dump
    has to neutralize both sources; otherwise ``AuthSettings`` resolves two
    providers, refuses to build, and ``make regen-specs`` cannot run at all.

    This test supplies the hostile environment the sibling freshness test cannot:
    that one inherits the pins ``pyproject.toml`` already sets for pytest.
    """
    dotenv = tmp_path / "developer.env"
    dotenv.write_text(
        "AUTH__PROVIDER='{\"casdoor\": null}'\n"
        "AUTH__PROVIDER__GRAFANA__ENDPOINT=https://grafana.invalid/graph\n"
        "AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN=token\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(DUMP_SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "ENV_FILE": str(dotenv),
            "AUTH__PROVIDER__GRAFANA__VERIFY_SSL": "false",
        },
    )
    assert "auth provider" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr
