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

"""Guard that the committed frontend OpenAPI spec fixtures match the backend."""

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
