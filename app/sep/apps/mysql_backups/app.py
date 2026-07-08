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

"""Wire the MySQL Backups plugin as a declarative ``TaskExecutionApp``.

This definition replaces the hand-written JSON API router and schema: the
registry discovers the exported ``app`` and mounts its derived router, which
serves the byte-identical schema, list, detail, create, update, execute, and
delete surfaces. Create and update are derived from the model-first
:class:`~app.sep.apps.mysql_backups.models.BackupCreate` through the
``run-python`` spec builder, with the ``backup_type``-aware
:func:`~app.sep.apps.mysql_backups.deps.build_mysql_backups_api_task_response`
stamping ``backup_type`` / ``hostname`` on list, detail, and create; delete is
the framework's plain default. The display fields (``display_name`` / ``uri_path``
/ ``css_class``) are supplied here because ``settings.yaml`` no longer carries
them. The Jinja UI router is threaded explicitly as ``jinja_router``; the
registry does not. The restore subpackage is a structurally-bound child app
declared via ``child_apps`` (key ``mysql_backups/restore``), so it is mounted and
toggled with this parent rather than as an independent ``settings.yaml`` entry or
a sub-router here.
"""

from app.core.pagination.deps import make_pagination_dep
from app.sep.apps.framework.apps import (
    AppCapabilities,
    ListFilterConfig,
    TaskExecutionApp,
)
from app.sep.apps.framework.schema import RelatedApp
from app.sep.apps.mysql_backups.deps import build_mysql_backups_api_task_response
from app.sep.apps.mysql_backups.models import (
    BackupCreate,
    BackupResponse,
)
from app.sep.apps.mysql_backups.restore.app import app as restore_app
from app.sep.apps.mysql_backups.routes import router as jinja_router
from app.sep.apps.mysql_backups.spec import build_backup_spec
from app.sep.apps.mysql_backups.views import mysql_backups_views
from app.tasks.models import TaskOwner

MYSQL_BACKUPS_MAX_PAGINATION_LIMIT = 50

app = TaskExecutionApp(
    name="mysql_backups",
    display_name="MySQL Backups",
    uri_path="/mysql_backups",
    css_class="mysql_backups",
    group="backups",
    nav_order=8,
    description="Run XtraBackup, Mydumper, and Binlog backups against MySQL hosts.",
    owner=TaskOwner.BACKUPS,
    create_model=BackupCreate,
    response_model=BackupResponse,
    views=mysql_backups_views,
    task_spec_builder=build_backup_spec,
    response_builder=build_mysql_backups_api_task_response,
    pagination=make_pagination_dep(max_limit=MYSQL_BACKUPS_MAX_PAGINATION_LIMIT),
    capabilities=AppCapabilities(update=True, delete=True),
    list_filter=ListFilterConfig(status=True),
    related_apps=(
        RelatedApp(
            app_key="mysql_backups/restore",
            label="Restore",
            route_segment="restores",
        ),
    ),
    jinja_router=jinja_router,
    child_apps=(restore_app,),
)
