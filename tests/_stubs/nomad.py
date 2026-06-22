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

"""Canonical stub for the Nomad orchestrator.

Pattern reference for milestone M4. The actual consolidation work pulls the
Nomad stubs currently scattered across plugin-level ``conftest.py`` modules
into a single fixture surface exposed from here, with payloads recorded
against staging via ``vcrpy``. Until then this module documents the
contract by example so plugin authors know where canonical stubs will live.

Usage from a test::

    from tests._stubs.nomad import patch_nomad_dispatch

    def test_something(mocker):
        patch_nomad_dispatch(mocker, allocation_id="alloc-abc")
        ...

Companion modules: ``tests._stubs.casdoor`` and ``tests._stubs.pmm``.
"""

from typing import Any

from pytest_mock import MockerFixture


def patch_nomad_dispatch(
    mocker: MockerFixture,
    *,
    allocation_id: str = "alloc-test-0001",
    dispatched_job_id: str | None = None,
) -> dict[str, Any]:
    """Patch the Nomad executor's dispatch surface with a deterministic response.

    Reference shape only — the production stub will expand to allocation
    polling, log streaming, and signal handling once milestone M4 lands. The
    return value is the dispatch payload the production code consumes, so
    tests can assert against it. ``NomadExecutor.dispatch_job`` is synchronous,
    so it is patched with a plain ``MagicMock``.

    :param mocker: The ``pytest-mock`` fixture from the calling test.
    :type mocker: pytest_mock.MockerFixture
    :param allocation_id: The deterministic allocation id used everywhere
        a real Nomad allocation id would appear.
    :type allocation_id: str
    :param dispatched_job_id: The dispatched-job id; defaults to a derived
        value when not provided.
    :type dispatched_job_id: str | None
    :return: The payload the Nomad executor would return on dispatch.
    :rtype: dict[str, Any]
    """
    payload: dict[str, Any] = {
        "DispatchedJobID": dispatched_job_id or f"job/{allocation_id}",
        "EvalID": "eval-test-0001",
        "Index": 1,
    }
    mocker.patch(
        "app.tasks.execution.executors.nomad.models.NomadExecutor.dispatch_job",
        new=mocker.MagicMock(return_value=payload),
    )
    return payload
