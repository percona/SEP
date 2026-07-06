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

"""Wire the PtMysqlSummary plugin as a declarative ``TaskExecutionApp``."""

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import get_username_mapping
from app.sep.plugins.pt_mysql_summary.models import PtMysqlSummaryForm, PtMysqlSummaryTaskResponse
from app.sep.plugins.pt_mysql_summary.spec import build_pt_mysql_summary_spec
from app.sep.plugins.pt_mysql_summary.views import pt_mysql_summary_views
from app.sep.plugins.framework.apps import AppCapabilities, TaskExecutionApp
from app.tasks.models import TaskOwner

app = TaskExecutionApp(
    name="pt_mysql_summary",
    display_name="MySQL Summary",
    uri_path="/mysql-summary",
    nav_order=21,
    description="Run pt-mysql-summary against a Percona-managed MySQL host.",
    owner=TaskOwner.PT_MYSQL_SUMMARY,  # add PT_MYSQL_SUMMARY to TaskOwner in app/tasks/models.py
    create_model=PtMysqlSummaryForm,
    response_model=PtMysqlSummaryTaskResponse,
    views=pt_mysql_summary_views,
    task_spec_builder=build_pt_mysql_summary_spec,
    capabilities=AppCapabilities(create=True, execute=True, update=True, delete=True),
    service_type=ServiceTypeEnum.MYSQL,
    list_status_filter=True,
    list_service_type_filter=True,
    response_context_provider=get_username_mapping,
)
