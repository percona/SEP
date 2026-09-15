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

"""Convert between ``models.py``'s persisted shape and ``strategy.py``'s typed shape.

Split out of ``models.py`` specifically so it *can* import
:mod:`~app.sep.apps.om_bootstrap.strategy` -- ``models.py`` cannot, since Alembic
loads it in isolation and any import through the ``om_bootstrap`` package path
drags in the whole framework (see ``models.py``'s module docstring). This module
carries no such restriction: nothing here is Alembic-loaded.

Also where ``models.py``'s spelled-again ``InstallMethod``/``OperatingSystem``
enums are checked against ``strategy.py``'s real ones, so the two cannot drift
apart silently.
"""

from typing import Any

from app.sep.apps.om_bootstrap import models
from app.sep.apps.om_bootstrap.models import BootstrapRun
from app.sep.apps.om_bootstrap.strategy import (
    HostBootstrapState,
    InstallMethod,
    OperatingSystem,
)

__all__ = ["dump_host_states", "parse_host_states"]


def _assert_enums_match() -> None:
    """Fail at import time if ``models.py``'s spelled-again enums drift.

    Cheap and load-bearing: the alternative is a silently wrong Alembic column
    constraint (``models.py``'s copy) that only surfaces the day someone adds a
    strategy needing a new :class:`InstallMethod` or :class:`OperatingSystem`
    member and the persisted column rejects it.
    """
    expected_methods = {member.value for member in InstallMethod}
    actual_methods = {member.value for member in models.InstallMethod}
    if expected_methods != actual_methods:
        raise AssertionError(
            f"models.InstallMethod {actual_methods} has drifted from "
            f"strategy.InstallMethod {expected_methods}"
        )
    expected_os = {member.value for member in OperatingSystem}
    actual_os = {member.value for member in models.OperatingSystem}
    if expected_os != actual_os:
        raise AssertionError(
            f"models.OperatingSystem {actual_os} has drifted from "
            f"strategy.OperatingSystem {expected_os}"
        )


_assert_enums_match()


def parse_host_states(run: BootstrapRun) -> list[HostBootstrapState]:
    """Parse a run's persisted ``hosts`` document back into typed state.

    :param run: The run whose ``hosts`` document to parse.
    :return: One :class:`~app.sep.apps.om_bootstrap.strategy.HostBootstrapState`
        per persisted entry, in the order they were stored.
    """
    return [HostBootstrapState.model_validate(entry) for entry in run.hosts]


def dump_host_states(states: list[HostBootstrapState]) -> list[dict[str, Any]]:
    """Dump typed host states into the plain-JSON shape :attr:`BootstrapRun.hosts` stores.

    ``mode="json"``: datetimes on
    :class:`~app.sep.apps.om_bootstrap.strategy.StepRecord` dump to ISO-8601
    strings rather than ``datetime`` objects, which is what the JSON column
    actually stores and what :func:`parse_host_states` expects back.

    :param states: The host states to persist.
    :return: One plain-JSON dict per host, in the same order.
    """
    return [state.model_dump(mode="json") for state in states]
