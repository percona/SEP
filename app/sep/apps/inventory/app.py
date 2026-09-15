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

"""Wire the Inventory plugin as a declarative ``BaseApp``.

Register the bespoke inventory plugin through the registry's definition path
instead of the synthesized-legacy fallback. The app ships no browser surface:
it declares no ``AppSchema`` and stays out of the sidebar, exposing only the
operator API under ``/api/apps/inventory/``.
"""

import json

from app.sep.apps.framework.base import AppPeriodicTask, BaseApp
from app.sep.apps.inventory.api_routes import router as api_router
from app.sep.apps.inventory.config import inventory_app_settings
from app.tasks.models import INVENTORY_COLLECTION_TASK_NAME

COLLECTION_SCHEDULE_NAME = "sep__inventory_collection"


def _collection_task() -> AppPeriodicTask:
    """Declare the tombstone-collection beat entry this app owns.

    ``inventory-collection`` is a ``Task`` row rather than a Celery function, so
    the entry is ``qualified``: it points at the tasks service's
    ``execute_task_by_name`` and names the task in ``kwargs``. That is the same
    indirection an operator-created schedule uses, and the shape that puts the
    job in this plugin's task list.

    An unset interval contributes no schedule at all, which is the shipped
    default: collection deletes rows irreversibly, so a deployment carrying that
    default does not start doing so on upgrade.

    :return: The app's collection schedule contribution.
    """
    kwargs = {
        "task_name": INVENTORY_COLLECTION_TASK_NAME,
        "periodic_task_name": COLLECTION_SCHEDULE_NAME,
    }
    return AppPeriodicTask(
        name=COLLECTION_SCHEDULE_NAME,
        task="app.tasks.celery.execute_task_by_name",
        schedule=lambda: inventory_app_settings.COLLECTION_INTERVAL,
        extra_kwargs={"kwargs": json.dumps(kwargs)},
        qualified=True,
    )


app = BaseApp(
    name="inventory",
    display_name="Inventory",
    uri_path="/inventory",
    css_class="inventory",
    api_router=api_router,
    sidebar=False,
    periodic_task_schedules=[_collection_task()],
)
