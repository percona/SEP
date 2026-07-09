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

"""Wire the PostgreSQL Backups plugin as a declarative ``TaskExecutionApp``.

This definition replaces the hand-written JSON API router and schema: the
registry discovers the exported ``app`` and mounts its derived router, which
serves the schema, list, detail, create, execute, and delete surfaces, plus a
net-new ``PUT /{task_name}`` update route. The derived ``GET /schema`` matches
the legacy one except that it now surfaces the stanza name validation pattern,
which the legacy hand-written schema enforced server-side only. Create and update are
derived from the model-first
:class:`~app.sep.apps.backup_pg.models.BackupPgForm` through the ``run-python``
pgBackRest spec builder, with the YAML-config-derived
:func:`~app.sep.apps.backup_pg.deps.build_backup_pg_api_task_response` /
:func:`~app.sep.apps.backup_pg.deps.build_backup_pg_api_detail_response`
stamping ``hostname`` / ``backup_type`` (and ``host`` / ``port`` on detail) so
the list, detail, create, and update bodies stay byte-identical. Delete is the
framework's plain default; the body-reading running-conflict guard rides on the
derived create via ``create_extra_deps``, and the protected-task +
running-conflict guards ride on the derived PUT via ``update_guard``. The Jinja
UI router is threaded explicitly as ``jinja_router``; the registry does not.
"""

from fastapi import Depends

from app.core.pagination.deps import make_pagination_dep
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_pg.deps import (
    build_backup_pg_api_detail_response,
    build_backup_pg_api_task_response,
    get_unprotected_backups_task,
    HasNoConflictedRunningTasksOnCreate,
)
from app.sep.apps.backup_pg.models import (
    BackupPgForm,
    BackupTaskDetailResponse,
    BackupTaskResponse,
    OWNER,
)
from app.sep.apps.backup_pg.routes import router as jinja_router
from app.sep.apps.backup_pg.spec import build_backup_pg_spec
from app.sep.apps.backup_pg.views import backup_pg_views
from app.sep.apps.framework.apps import (
    AppCapabilities,
    ListFilterConfig,
    TaskExecutionApp,
)
from app.sep.deps import HasNoConflictedRunningTasks

app = TaskExecutionApp(
    name="backup_pg",
    display_name="PostgreSQL Backups",
    uri_path="/backup_pg",
    css_class="backup_pg",
    group="backups",
    nav_order=10,
    description=(
        "Configure pgBackRest-based PostgreSQL backups and run incremental "
        "or differential backup tasks against a Percona-managed Postgres host."
    ),
    owner=OWNER,
    create_model=BackupPgForm,
    response_model=BackupTaskResponse,
    views=backup_pg_views,
    task_spec_builder=build_backup_pg_spec,
    capabilities=AppCapabilities(update=True, delete=True),
    service_type=ServiceTypeEnum.POSTGRESQL,
    pagination=make_pagination_dep(),
    list_filter=ListFilterConfig(status=True),
    response_builder=build_backup_pg_api_task_response,
    detail_response_builder=build_backup_pg_api_detail_response,
    detail_response_model=BackupTaskDetailResponse,
    create_extra_deps=(HasNoConflictedRunningTasksOnCreate,),
    update_guard=(Depends(get_unprotected_backups_task), HasNoConflictedRunningTasks),
    delete_guard=(HasNoConflictedRunningTasks,),
    jinja_router=jinja_router,
)
