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

"""Wire the Example plugin as a declarative ``TaskExecutionApp``."""

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import get_username_mapping
from app.sep.plugins.example.models import ExampleForm, ExampleTaskResponse
from app.sep.plugins.example.spec import build_example_spec
from app.sep.plugins.example.views import example_views
from app.sep.plugins.framework.apps import AppCapabilities, TaskExecutionApp
from app.tasks.models import TaskOwner

app = TaskExecutionApp(
    name="example",
    display_name="Example",
    uri_path="/example",
    nav_order=20,
    description="Run example-tool against a Percona-managed MySQL host.",
    owner=TaskOwner.EXAMPLE,  # add EXAMPLE to TaskOwner in app/tasks/models.py
    create_model=ExampleForm,
    response_model=ExampleTaskResponse,
    views=example_views,
    task_spec_builder=build_example_spec,
    capabilities=AppCapabilities(create=True, execute=True, update=True, delete=True),
    service_type=ServiceTypeEnum.MYSQL,
    list_status_filter=True,
    list_service_type_filter=True,
    response_context_provider=get_username_mapping,
)
