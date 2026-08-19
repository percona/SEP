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

import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.tasks.execution.executors import nomad

REPO_ROOT = Path(__file__).resolve().parents[6]
_CHILD_TIMEOUT_SEC = 300

# Derived from the package rather than enumerated, so a submodule added later
# cannot join the package without also joining this regression test.
_SUBMODULES = tuple(
    f"{nomad.__name__}.{module.name}" for module in pkgutil.iter_modules(nomad.__path__)
)


def test_submodule_probe_list_is_not_vacuous() -> None:
    """Assert the derived submodule list is non-empty."""
    assert _SUBMODULES, "discovered no submodules -- the probes below would be vacuous"


@pytest.mark.parametrize("submodule", _SUBMODULES)
def test_nomad_submodule_imports_without_config_first(submodule: str) -> None:
    """Assert ``submodule`` imports cleanly when nothing has imported config yet.

    Live entrypoints usually import ``app.tasks.config`` first, which hid a real
    cycle: package ``__init__`` -> ``models`` -> ``config`` -> package
    ``NomadExecutor``. Each submodule gets its own interpreter so a sibling
    already sitting in ``sys.modules`` cannot resolve the cycle on its behalf.

    :param submodule: The dotted path of the submodule imported first.
    """
    probe = (
        "import importlib\n"
        f"importlib.import_module({submodule!r})\n"
        "from app.tasks.execution.executors.nomad import NomadExecutor\n"
        "assert NomadExecutor.__name__ == 'NomadExecutor'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_SEC,
        check=False,
    )
    assert result.returncode == 0, (
        f"{submodule} failed to import first in a clean interpreter:\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
