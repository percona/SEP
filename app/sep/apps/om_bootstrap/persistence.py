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
    StepRecord,
)

__all__ = [
    "dump_host_states",
    "dump_run_steps",
    "parse_host_states",
    "parse_run_steps",
    "to_models_install_method",
    "to_models_os",
    "to_strategy_install_method",
    "to_strategy_os",
]


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


def to_strategy_install_method(value: models.InstallMethod) -> InstallMethod:
    """Convert a persisted ``models.InstallMethod`` to ``strategy.py``'s real one.

    A ``BootstrapRun.install_method`` read off a query is ``models.py``'s
    spelled-again enum, not ``strategy.py``'s -- Pydantic coerces one into the
    other by value silently at runtime (they are two distinct classes with the
    same string values), which is precisely the kind of implicit conversion
    worth making explicit and type-checked instead of relying on. Safe by
    :func:`_assert_enums_match`'s own invariant: every value here is guaranteed
    to be a valid member of both enums.

    :param value: The persisted enum value.
    :return: The equivalent ``strategy.py`` member.
    """
    return InstallMethod(value.value)


def to_strategy_os(value: models.OperatingSystem) -> OperatingSystem:
    """Convert a persisted ``models.OperatingSystem`` to ``strategy.py``'s real one.

    See :func:`to_strategy_install_method` -- same reasoning, same guarantee.

    :param value: The persisted enum value.
    :return: The equivalent ``strategy.py`` member.
    """
    return OperatingSystem(value.value)


def to_models_install_method(value: InstallMethod) -> models.InstallMethod:
    """Convert a ``strategy.py`` install method to ``models.py``'s spelled-again one.

    The reverse of :func:`to_strategy_install_method`, needed when constructing
    a new :class:`BootstrapRun` from a request typed against ``strategy.py``'s
    enum. Same by-value guarantee.

    :param value: The strategy-typed value.
    :return: The equivalent ``models.py`` member.
    """
    return models.InstallMethod(value.value)


def to_models_os(value: OperatingSystem) -> models.OperatingSystem:
    """Convert a ``strategy.py`` OS to ``models.py``'s spelled-again one.

    See :func:`to_models_install_method` -- same reasoning, same guarantee.

    :param value: The strategy-typed value.
    :return: The equivalent ``models.py`` member.
    """
    return models.OperatingSystem(value.value)


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


def parse_run_steps(run: BootstrapRun) -> list[StepRecord]:
    """Parse a run's persisted ``run_steps`` document back into typed records.

    The run-level counterpart of :func:`parse_host_states` -- same shape, same
    "read whole" treatment, just not scoped to any one host (see
    :attr:`~app.sep.apps.om_bootstrap.models.BootstrapRun.run_steps`'s own
    docstring).

    :param run: The run whose ``run_steps`` document to parse.
    :return: One :class:`~app.sep.apps.om_bootstrap.strategy.StepRecord` per
        persisted entry, in the order they were stored.
    """
    return [StepRecord.model_validate(entry) for entry in run.run_steps]


def dump_run_steps(steps: list[StepRecord]) -> list[dict[str, Any]]:
    """Dump typed run-level steps into the plain-JSON shape ``run_steps`` stores.

    See :func:`dump_host_states` -- same ``mode="json"`` reasoning.

    :param steps: The run-level steps to persist.
    :return: One plain-JSON dict per step, in the same order.
    """
    return [step.model_dump(mode="json") for step in steps]
