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

"""Assert the derived checksums routes assemble the byte-exact ``pt-table-checksum`` args.

These exercise the real FastAPI body-parsing → ``ChecksumsForm`` → spec-builder →
``build_command_args`` path over HTTP without overriding the create-body dep, so a
regression in the declarative arg assembly surfaces here rather than in production.
"""

from fastapi import status

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.checksums.app import app as checksums_app
from tests.app.factories import MOCK_CREATED_SERVICE_ID
from tests.app.sep.apps.framework.contract_suite import (
    app_base_url,
    build_contract_client,
)
from tests.app.sep.apps.framework.kit import (
    MockInventoryAPI,
    MockTaskAPI,
    SYNTH_EXECUTOR_HOST,
    SYNTH_SERVICE_HOST,
    SYNTH_SERVICE_PORT,
)

_DSN_PREFIX = f"h={SYNTH_SERVICE_HOST},P={SYNTH_SERVICE_PORT},"


def test_derived_create_assembles_exact_args(regular_user: CasdoorUser) -> None:
    """Assert ``POST /api/apps/checksums/`` assembles the byte-exact args string."""
    tasks_api = MockTaskAPI()
    client = build_contract_client(
        checksums_app,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=MockInventoryAPI(),
    )

    response = client.post(
        f"{app_base_url(checksums_app)}/",
        json={
            "task_name": "chk-derived",
            "hostname": SYNTH_EXECUTOR_HOST,
            "service_id": MOCK_CREATED_SERVICE_ID,
            "recursion_method": "processlist",
            "databases": "db1,db2",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    meta = tasks_api.last_create_payload["data"]["meta"]
    assert meta["command"] == "pt-table-checksum"
    assert (
        meta["args"]
        == f"{_DSN_PREFIX} --recursion-method=processlist --databases=db1,db2"
    )


def test_derived_update_assembles_exact_args(regular_user: CasdoorUser) -> None:
    """Assert ``PUT /api/apps/checksums/{task_name}`` reuses the arg assembly."""
    tasks_api = MockTaskAPI()
    tasks_api.seed_task("chk-update", owner=checksums_app.owner)
    client = build_contract_client(
        checksums_app,
        user=regular_user,
        tasks_api=tasks_api,
        inventory_api=MockInventoryAPI(),
    )

    response = client.put(
        f"{app_base_url(checksums_app)}/chk-update",
        json={
            "task_name": "chk-update",
            "hostname": SYNTH_EXECUTOR_HOST,
            "service_id": MOCK_CREATED_SERVICE_ID,
            "recursion_method": "hosts",
            "tables": "db.t1",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert (
        response.json()["data"]["meta"]["args"]
        == f"{_DSN_PREFIX} --recursion-method=hosts --tables=db.t1"
    )


def test_derived_schema_advanced_section_field_order(regular_user: CasdoorUser) -> None:
    """Assert ``GET /api/apps/checksums/schema`` keeps the Advanced display order."""
    client = build_contract_client(
        checksums_app,
        user=regular_user,
        tasks_api=MockTaskAPI(),
        inventory_api=MockInventoryAPI(),
    )

    response = client.get(f"{app_base_url(checksums_app)}/schema")

    assert response.status_code == status.HTTP_200_OK
    advanced = next(
        form for form in response.json()["forms"] if form["title"] == "Advanced"
    )
    assert [field["name"] for field in advanced["fields"]] == [
        "pause_file",
        "progress",
        "set_vars",
        "max_load",
        "chunk_time",
        "max_lag",
    ]
