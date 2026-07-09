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

"""Guard the per-app service-type wiring of every owning app's index context.

``get_tasks_context`` no longer derives the inventory service type from the
owner; each ``get_<app>_index_context`` passes an explicit ``service_type``
literal at the call site. This pins that literal per app, so the four apps whose
``TaskExecutionApp.service_type`` is ``None`` (they pass the literal directly)
cannot silently regress to an unscoped ``/services/`` fetch.
"""

from unittest.mock import AsyncMock

import pytest

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.alters.deps import get_alters_index_context
from app.sep.apps.archives.deps import get_archives_index_context
from app.sep.apps.backup_mongo.deps import (
    get_backups_index_context as get_backup_mongo_index_context,
)
from app.sep.apps.backup_mongo.restore.deps import (
    get_restores_index_context as get_restore_mongo_index_context,
)
from app.sep.apps.backup_pg.deps import (
    get_backups_index_context as get_backup_pg_index_context,
)
from app.sep.apps.checksums.deps import get_checksums_index_context
from app.sep.apps.mysql_backups.deps import (
    get_backups_index_context as get_mysql_backups_index_context,
)
from app.sep.apps.mysql_backups.restore.deps import (
    get_restores_index_context as get_mysql_restores_index_context,
)
from app.sep.deps import ExecutorHostsContext

_EMPTY_PAGE = {"items": [], "total": 0, "offset": 0, "limit": 50}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("index_context", "expected_service_type"),
    [
        (get_alters_index_context, ServiceTypeEnum.MYSQL),
        (get_archives_index_context, ServiceTypeEnum.MYSQL),
        (get_backup_mongo_index_context, ServiceTypeEnum.MONGODB),
        (get_restore_mongo_index_context, ServiceTypeEnum.MONGODB),
        (get_backup_pg_index_context, ServiceTypeEnum.POSTGRESQL),
        (get_checksums_index_context, ServiceTypeEnum.MYSQL),
        (get_mysql_backups_index_context, ServiceTypeEnum.MYSQL),
        (get_mysql_restores_index_context, ServiceTypeEnum.MYSQL),
    ],
)
async def test_index_context_scopes_services_fetch_by_service_type(
    index_context, expected_service_type
) -> None:
    """Drive each app's index context and assert its ``/services/`` fetch scope."""
    inventory_api = AsyncMock()
    inventory_api.get = AsyncMock(return_value=_EMPTY_PAGE)
    tasks_api = AsyncMock()
    tasks_api.get = AsyncMock(return_value=_EMPTY_PAGE)
    executor_hosts_ctx = ExecutorHostsContext(hosts={}, display_names={})

    await index_context(inventory_api, tasks_api, {}, executor_hosts_ctx)

    services_calls = [
        call
        for call in inventory_api.get.await_args_list
        if call.args and call.args[0] == "/services/"
    ]
    assert services_calls, "index context never fetched /services/"
    assert services_calls[0].kwargs["params"]["service_type"] == expected_service_type
