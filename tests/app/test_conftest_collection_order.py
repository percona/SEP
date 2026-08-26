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

"""Regression guard for order-dependent loss of ``tests/app/sep/conftest.py`` fixtures.

A single-process ``pytest`` run given an explicit file list where a shallow
``tests/app``-level module sits between two deep ``tests/app/sep/**`` modules used to
drop every fixture defined in ``tests/app/sep/conftest.py`` for the second deep module,
raising ``fixture 'test_client' not found``. The fixtures now resolve from the
always-loaded ancestor ``tests/app/conftest.py``, so ordering no longer matters.

Each case spawns a child ``pytest`` because the fragility only reproduces across an
explicit multi-file, single-process invocation — it cannot be expressed as an in-process
fixture assertion.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Variables the child run must not inherit. ``-o addopts=`` clears the ini
# option but not ``PYTEST_ADDOPTS``, which the pre-push gate uses to inject its
# checkpoint plugin; the child would then deselect every node id the outer run
# already verified, collect nothing, and exit 5 on a resumed push.
_INHERITED_PYTEST_VARS = ("PYTEST_ADDOPTS", "SEP_PREPUSH_CHECKPOINT")

PMM = "tests/app/sep/clients/test_pmm.py"
CELERY = "tests/app/test_celery_signals.py"
MAIN = "tests/app/test_main.py"
DOWNLOAD = "tests/app/sep/routes/test_download_files.py"

ORDERINGS = [
    # Shallow module between two deep sep modules — the two failing orderings.
    pytest.param([PMM, CELERY, DOWNLOAD], id="deep-shallow-deep-celery"),
    pytest.param([PMM, MAIN, DOWNLOAD], id="deep-shallow-deep-main"),
    # Positive control: shallow last was always clean; assert it stays clean.
    pytest.param([DOWNLOAD, PMM, CELERY], id="control-shallow-last"),
]


@pytest.mark.parametrize("order", ORDERINGS)
def test_sep_conftest_fixtures_survive_collection_order(order: list[str]) -> None:
    """Assert the sep client/session fixtures resolve regardless of collection order.

    ``-k test_returns_file_metadata`` keeps the child run tiny: ``-k`` deselects after
    collection, so all three modules are still collected in the pathological order and the
    kept ``test_download_files.py`` case still runs setup — enough to surface a dropped
    fixture. ``-n0`` forces a single process, ``-o addopts=`` neutralises any future
    default opts, and ``--no-cov`` avoids clobbering the outer run's coverage data.

    :param order: The explicit file list handed to the child ``pytest`` process.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *order,
            "-n0",
            "--no-cov",
            "-o",
            "addopts=",
            "-k",
            "test_returns_file_metadata",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        env={
            key: value
            for key, value in os.environ.items()
            if key not in _INHERITED_PYTEST_VARS
        },
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert "fixture 'test_client' not found" not in combined, combined
    assert result.returncode == 0, combined
