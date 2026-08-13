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

"""Define the POM Discovery settings section.

Read straight off YAML/env under ``SEP.POM_DISCOVERY`` rather than mounted as a field
on ``SEPSettings``, for the same reason the other app sections do it: importing this module
runs the package ``__init__``, which pulls in the app definition and transitively
``sep_settings``, so a field default typed with this class would cycle while
``SEPSettings`` is still under construction.
"""

__all__ = ["PomDiscoverySettings", "pom_discovery_settings"]

from datetime import timedelta
from typing import Annotated, ClassVar

from annotated_types import Gt
from pydantic import PositiveInt

from app.core.celery.models import IntervalSchedule, Period
from app.core.config import BaseYamlSettings
from app.core.utils.fields import TimedeltaSeconds


class PomDiscoverySettings(BaseYamlSettings):
    """Configure the on-host probe.

    The defaults assume the consumer is PMM polling :func:`get_facts`, which serves
    whatever the last completed probe stored. That is why ``SCHEDULE`` matters more
    here than it does for a job someone triggers by hand: nothing else makes the
    facts appear, and a puller must never be the thing that waits for a Nomad job.

    :cvar SETTINGS_PREFIXES: Places this section under ``SEP.POM_DISCOVERY``.
    :param SCHEDULE: How often the probe sweeps the estate. ``None`` unregisters the
        periodic job, leaving the trigger endpoint as the only way facts are refreshed.
    :param PROBE_DATABASE: Whether the payload connects to mongod and runs database
        commands. False collects process and OS facts only, which needs no credentials
        -- and still yields ``installed_version``, the field this app exists for.
    :param CREDENTIALS_PATH: Node-side file holding the MongoDB URI to take credentials
        from. ``None`` falls back to ``~/.mongodb_uri``, the same file the PBM payloads
        read.
    :param CONNECT_TIMEOUT: Per-target connect and server-selection timeout, seconds.
    :param TASK_TIMEOUT: How long to wait for one dispatched probe task to reach a
        terminal status before giving up on it, seconds.
    :param POLL_INTERVAL: Delay between task-status polls, seconds.
    :param MAX_CONCURRENT_PROBES: Ceiling on probe tasks in flight at once. Every
        dispatch is a Nomad job, and a real estate has far more hosts than this
        workspace's sandbox.
    :param FACTS_MAX_AGE: How old the stored facts may be before :func:`get_facts`
        reports them stale. Not a filter -- stale facts are still served, with their
        age, because the consumer merges them by precedence and can decide for itself.
    :param RUN_RETENTION: How many runs to keep. Each carries its whole fact set, so
        this bounds the table rather than an operator having to.
    :param STALE_RUN_AFTER: How long a run may stay ``running`` before the trigger
        endpoint concludes its worker is gone. Must comfortably exceed the slowest
        legitimate sweep: ``TASK_TIMEOUT`` per dispatch, ``MAX_CONCURRENT_PROBES`` at
        a time.
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["SEP", "POM_DISCOVERY"]

    SCHEDULE: IntervalSchedule | None = IntervalSchedule(
        every=10, period=Period.MINUTES
    )
    PROBE_DATABASE: bool = True
    CREDENTIALS_PATH: str | None = None
    CONNECT_TIMEOUT: PositiveInt = 5
    TASK_TIMEOUT: PositiveInt = 180
    POLL_INTERVAL: PositiveInt = 3
    MAX_CONCURRENT_PROBES: PositiveInt = 8
    FACTS_MAX_AGE: Annotated[TimedeltaSeconds, Gt(timedelta(0))] = timedelta(minutes=30)
    RUN_RETENTION: PositiveInt = 50
    STALE_RUN_AFTER: Annotated[TimedeltaSeconds, Gt(timedelta(0))] = timedelta(
        minutes=30
    )


pom_discovery_settings: PomDiscoverySettings = PomDiscoverySettings()
