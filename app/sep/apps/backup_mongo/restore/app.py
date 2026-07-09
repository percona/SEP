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

"""Wire the MongoDB Restores subpackage as a parent-bound ``TaskExecutionApp``.

The registry discovers this app through ``backup_mongo``'s ``child_apps`` rather
than a ``settings.yaml`` entry, so it is mounted and toggled exactly with its
parent: its JSON router serves at ``/api/apps/backup_mongo/restore/`` while the
existing Jinja UI keeps serving at ``/backup_mongo/restores/`` via the threaded
``jinja_router``. A restore is a task group (parent config plus restore / pbm-list
/ optional force-resync legs), so its ``update`` / ``delete`` act on the whole
cascade — the framework's single-task derived routes would orphan or stale the
legs — leaving only ``schema`` and ``execute`` derived; the union list, the
sibling-aggregating detail, and the cascade create / update / delete ride
``extra_routes`` with the derived ``list`` and ``detail`` suppressed so the custom
routes win. Because ``backup_mongo`` is a ``schema=`` app, the sibling-tab
``RelatedApp`` lives on its ``AppSchema`` (in ``backup_mongo/schema.py``), not
here. A child has no ``settings.yaml`` entry to stamp its identity, so ``key`` /
``name`` / ``uri_path`` are set explicitly; ``uri_path`` preserves the Jinja route
the ``pbm_restores_*`` handlers build their redirects against.
"""

from app.sep.apps.backup_mongo.restore.api_routes import router as restore_custom_router
from app.sep.apps.backup_mongo.restore.deps import (
    build_restore_mongo_api_task_response,
    get_restores_task,
)
from app.sep.apps.backup_mongo.restore.models import OWNER, RestoreTaskResponse
from app.sep.apps.backup_mongo.restore.routes import router as jinja_router
from app.sep.apps.backup_mongo.restore.schema import restore_mongo_schema
from app.sep.apps.framework.apps import AppCapabilities, TaskExecutionApp

app = TaskExecutionApp(
    key="backup_mongo/restore",
    name="backup_mongo_restores",
    display_name="MongoDB Restores",
    uri_path="/backup_mongo/restores",
    css_class="backup_mongo",
    group="backups",
    nav_order=9,
    sidebar=False,
    parent_key="backup_mongo",
    owner=OWNER,
    schema=restore_mongo_schema,
    response_model=RestoreTaskResponse,
    response_builder=build_restore_mongo_api_task_response,
    get_task=get_restores_task,
    capabilities=AppCapabilities(
        create=False,
        detail=False,
        list=False,
        execute=True,
        update=False,
        delete=False,
    ),
    extra_routes=(restore_custom_router,),
    jinja_router=jinja_router,
)
