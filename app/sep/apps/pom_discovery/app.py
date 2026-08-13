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

"""Register POM Discovery as a ``BaseApp``.

The first of the SEP apps that exist to do work on Nomad clients. This one only
reads -- it runs a payload on each database host and collects facts no metric
carries -- but it establishes the shape the rest will follow: a periodic sweep, a
run history, and an API a consumer polls rather than drives.

``sidebar=False`` and no ``react_route``: there is nothing to navigate to. The
consumer is PMM's POM service polling ``GET /facts``, and the run history is for
diagnosis through the API. Registering it as an app is still what earns the Celery
module inclusion, the app-drain ownership tag, and the switch on the Apps page.
"""

from typing import cast

from app.core.celery.models import IntervalSchedule
from app.sep.apps.framework.base import AppPeriodicTask, BaseApp
from app.sep.apps.nav_icons import NavIcon
from app.sep.apps.pom_discovery.api_routes import router as api_router
from app.sep.apps.pom_discovery.config import pom_discovery_settings
from app.sep.apps.pom_discovery.schema import pom_discovery_schema


def _pom_discovery_periodic_tasks() -> list[AppPeriodicTask]:
    """Contribute the periodic sweep while it is configured.

    A callable rather than a list literal because ``SCHEDULE`` may be ``None`` to
    unregister the sweep, so the contribution is variable-length and a literal would
    commit to a fixed set at ``BaseApp(...)`` construction.

    The sweep is what makes ``GET /facts`` answerable at all: the endpoint never
    probes, so with no schedule the facts only ever change when someone posts to
    ``/runs``.

    :return: The sweep contribution, or an empty list when it is disabled.
    """
    if pom_discovery_settings.SCHEDULE is None:
        return []
    return [
        AppPeriodicTask(
            name="sep__run_pom_probe",
            task="run_pom_probe",
            schedule=lambda: cast("IntervalSchedule", pom_discovery_settings.SCHEDULE),
        ),
    ]


app = BaseApp(
    name="pom_discovery",
    display_name="POM Discovery",
    uri_path="/pom_discovery",
    css_class="pom_discovery",
    group="diagnostics",
    sidebar=False,
    nav_icon=NavIcon.MONGO,
    api_router=api_router,
    schema=pom_discovery_schema,
    custom_ui=True,
    periodic_task_schedules=_pom_discovery_periodic_tasks,
)
