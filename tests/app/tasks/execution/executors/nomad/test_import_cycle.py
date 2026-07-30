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

"""Regression tests for the Nomad executor package import cycle."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]

# Submodules that must load in a clean interpreter without importing
# ``app.tasks.config`` first. ``models`` is the heavy end of the former cycle;
# ``exceptions`` is a light sibling that still executes package ``__init__``.
_SUBMODULES = (
    "app.tasks.execution.executors.nomad.exceptions",
    "app.tasks.execution.executors.nomad.models",
)


def test_nomad_package_submodules_import_without_config_first() -> None:
    """Assert any Nomad executor submodule imports cleanly before tasks config.

    Live entrypoints usually import ``app.tasks.config`` first, which hid a real
    cycle: package ``__init__`` → ``models`` → ``config`` → package
    ``NomadExecutor``. A fresh interpreter that touches a submodule first must
    still succeed.
    """
    probe = (
        "import importlib\n"
        f"for name in {_SUBMODULES!r}:\n"
        "    importlib.import_module(name)\n"
        "from app.tasks.execution.executors.nomad import NomadExecutor\n"
        "assert NomadExecutor.__name__ == 'NomadExecutor'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"Nomad package submodule import failed in a clean interpreter:\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
