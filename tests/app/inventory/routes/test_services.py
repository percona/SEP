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

"""Define tests for inventory service routes."""

from datetime import datetime, UTC

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.testclient import TestClient

from app.core.pagination import DEFAULT_PAGINATION_LIMIT
from app.inventory.crud import SchemaManager
from app.inventory.models import Node, Schema, Service, ServiceSystemObservation
from tests.app.factories import (
    NodeWriteFactory,
    SchemaWriteFactory,
    ServiceSystemObservationWriteFactory,
    ServiceWriteFactory,
)

OFFSET_BEYOND_TOTAL = 999
LIST_QUERY_MATCH_TOTAL = 2


class TestListServices:
    """Test GET /services/ endpoint."""

    def test_list_services_empty(self, test_client: TestClient) -> None:
        """Return an empty paginated response when no services exist."""
        response = test_client.get("/services/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["offset"] == 0
        assert data["limit"] == DEFAULT_PAGINATION_LIMIT

    def test_list_services_rejects_unknown_sort_key(
        self, test_client: TestClient
    ) -> None:
        """Reject an out-of-allowlist sort key with HTTP 422."""
        response = test_client.get("/services/", params={"sort": "evil"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_list_services_multiple(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return all services with schemas and node loaded."""
        response = test_client.get("/services/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["id"] == service.id
        assert "schemas" in data["items"][0]
        assert "node" in data["items"][0]

    def test_list_services_filter_by_service_type(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return only services matching the requested service type."""
        response = test_client.get(
            "/services/",
            params={"service_type": service.type},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) >= 1
        assert all(s["type"] == service.type for s in data["items"])

    def test_list_services_custom_offset(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return empty items when offset is beyond total."""
        response = test_client.get("/services/", params={"offset": OFFSET_BEYOND_TOTAL})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 1
        assert data["offset"] == OFFSET_BEYOND_TOTAL

    def test_list_services_custom_limit(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return limited items while total remains unchanged."""
        response = test_client.get("/services/", params={"limit": 1})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["limit"] == 1

    def test_list_services_filter_with_pagination(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return filtered total with pagination params."""
        response = test_client.get(
            "/services/",
            params={"service_type": service.type, "limit": 1},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) <= 1

    def test_list_services_search_ilike(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return only services whose name matches the search case-insensitively."""
        match = ServiceWriteFactory.build(name="AlphaSearchService", port=4401)
        other = ServiceWriteFactory.build(name="OtherService", port=4402)
        test_client.post(
            f"/nodes/{node.id}/services/", json=match.model_dump(mode="json")
        )
        test_client.post(
            f"/nodes/{node.id}/services/", json=other.model_dump(mode="json")
        )

        response = test_client.get("/services/", params={"search": "alphasearch"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == match.name

    def test_list_services_search_reports_filtered_total(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Filter rows by search and report the filtered total, not the page size."""
        for index, suffix in enumerate(("a", "b")):
            payload = ServiceWriteFactory.build(
                name=f"FilterMatchService_{suffix}",
                port=4500 + index,
            )
            test_client.post(
                f"/nodes/{node.id}/services/", json=payload.model_dump(mode="json")
            )
        other = ServiceWriteFactory.build(name="UnrelatedService", port=4599)
        test_client.post(
            f"/nodes/{node.id}/services/", json=other.model_dump(mode="json")
        )

        response = test_client.get(
            "/services/", params={"search": "filtermatchservice", "limit": 1}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == LIST_QUERY_MATCH_TOTAL
        assert len(data["items"]) == 1

    def test_list_services_deterministic_ordering_across_pages(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Sort equal names stably across pages via the id tie-breaker."""
        shared_name = "SameSortService"
        created_ids: list[int] = []
        for index in range(LIST_QUERY_MATCH_TOTAL):
            payload = ServiceWriteFactory.build(name=shared_name, port=4600 + index)
            create_response = test_client.post(
                f"/nodes/{node.id}/services/",
                json=payload.model_dump(mode="json"),
            )
            assert create_response.status_code == status.HTTP_201_CREATED
            created_ids.append(create_response.json()["id"])
        created_ids.sort()

        first_page = test_client.get(
            "/services/",
            params={"sort": "name", "search": shared_name, "limit": 1, "offset": 0},
        )
        second_page = test_client.get(
            "/services/",
            params={"sort": "name", "search": shared_name, "limit": 1, "offset": 1},
        )
        assert first_page.status_code == status.HTTP_200_OK
        assert second_page.status_code == status.HTTP_200_OK
        assert first_page.json()["items"][0]["id"] == created_ids[0]
        assert second_page.json()["items"][0]["id"] == created_ids[1]


class TestRetrieveService:
    """Test GET /services/{service_id} endpoint."""

    def test_retrieve_service(self, test_client: TestClient, service: Service) -> None:
        """Return the service with schemas and node."""
        response = test_client.get(f"/services/{service.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == service.id
        assert "schemas" in data
        assert "node" in data

    def test_retrieve_service_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent service ID."""
        response = test_client.get("/services/9999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUpdateService:
    """Test PUT /services/{service_id} endpoint."""

    def test_update_service(
        self, test_client: TestClient, service: Service, node: Node
    ) -> None:
        """Update a service name and return the updated service."""
        payload = ServiceWriteFactory.build(node_id=node.id)
        payload.name = "updated-service-name"
        response = test_client.put(
            f"/services/{service.id}",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "updated-service-name"

    def test_update_service_not_found(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return 404 when updating a nonexistent service."""
        payload = ServiceWriteFactory.build(node_id=node.id)
        response = test_client.put(
            "/services/9999",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_service_invalid_node_id(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return 400 when updating with a nonexistent node_id."""
        payload = ServiceWriteFactory.build(node_id=9999)
        response = test_client.put(
            f"/services/{service.id}",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Invalid node_id: 9999"

    def test_update_service_omitting_node_id_preserves_parent(
        self, test_client: TestClient, service: Service, node: Node
    ) -> None:
        """Apply a partial update that omits node_id, leaving the parent unchanged.

        A second node must exist: the omitted FK previously resolved to ``None``,
        and the parent pre-check drops ``None`` filters and matched every node, so
        with more than one node it raised ``MultipleResultsFound`` (HTTP 500).
        """
        second = test_client.post(
            "/nodes/", json=NodeWriteFactory.build().model_dump(mode="json")
        )
        assert second.status_code == status.HTTP_201_CREATED
        body = ServiceWriteFactory.build().model_dump(mode="json", exclude={"node_id"})
        body["name"] = "renamed-service"
        assert "node_id" not in body
        response = test_client.put(f"/services/{service.id}", json=body)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "renamed-service"
        assert data["node_id"] == node.id

    def test_update_service_change_node_id_to_valid_parent(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Reparent a service to another existing node and return 200."""
        new_node = test_client.post(
            "/nodes/", json=NodeWriteFactory.build().model_dump(mode="json")
        )
        assert new_node.status_code == status.HTTP_201_CREATED
        new_node_id = new_node.json()["id"]
        payload = ServiceWriteFactory.build(node_id=new_node_id)
        response = test_client.put(
            f"/services/{service.id}",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["node_id"] == new_node_id

    def test_update_service_explicit_null_node_id_rejected(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Reject an explicit null node_id (the FK column is non-nullable)."""
        body = ServiceWriteFactory.build().model_dump(mode="json")
        body["node_id"] = None
        response = test_client.put(f"/services/{service.id}", json=body)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Invalid node_id: None"

    def test_update_service_omitting_node_id_preserves_association(
        self, test_client: TestClient, service: Service, node: Node
    ) -> None:
        """Partial update without node_id succeeds and leaves the FK unchanged.

        A second node exists so the omitted-FK path cannot accidentally resolve a
        single arbitrary parent: the old override skipped the ``id=None`` filter and
        crashed with ``MultipleResultsFound`` once more than one parent was present.
        """
        test_client.post(
            "/nodes/", json=NodeWriteFactory.build().model_dump(mode="json")
        )
        payload = ServiceWriteFactory.build()
        body = payload.model_dump(mode="json", exclude={"node_id"})
        body["name"] = "renamed-without-node-id"
        response = test_client.put(f"/services/{service.id}", json=body)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "renamed-without-node-id"
        assert data["node_id"] == node.id

    def test_update_service_explicit_null_node_id(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return 400 when node_id is explicitly null on a non-nullable relationship."""
        payload = ServiceWriteFactory.build()
        body = payload.model_dump(mode="json")
        body["node_id"] = None
        response = test_client.put(f"/services/{service.id}", json=body)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Invalid node_id: None"


class TestDeleteService:
    """Test DELETE /services/{service_id} endpoint."""

    def test_delete_service(self, test_client: TestClient, service: Service) -> None:
        """Delete a service and confirm it is gone."""
        response = test_client.delete(f"/services/{service.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        response = test_client.get(f"/services/{service.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_service_not_found(self, test_client: TestClient) -> None:
        """Return 404 when deleting a nonexistent service."""
        response = test_client.delete("/services/9999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestListSchemasByService:
    """Test GET /services/{service_id}/schemas/ endpoint."""

    def test_list_schemas_by_service_empty(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return an empty paginated response when the service has no schemas."""
        response = test_client.get(f"/services/{service.id}/schemas/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["offset"] == 0
        assert data["limit"] == DEFAULT_PAGINATION_LIMIT

    def test_list_schemas_by_service_rejects_unknown_sort_key(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Reject an out-of-allowlist sort key with HTTP 422."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"sort": "evil"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_list_schemas_by_service(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return compact schemas without tables for the given service."""
        response = test_client.get(f"/services/{service.id}/schemas/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["id"] == schema.id
        assert "tables" not in data["items"][0]

    def test_list_schemas_by_service_search(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return only schemas whose name matches the search case-insensitively."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"search": schema.name[:3]},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == schema.id

    def test_list_schemas_by_service_search_no_match(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return empty paginated response when search does not match any schema."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"search": "nonexistent_schema_xyz"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_schemas_by_service_include_tables(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return schemas with nested tables when include_tables is set."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"include_tables": "true"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["id"] == schema.id
        assert "tables" in data["items"][0]

    def test_list_schemas_by_service_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent service ID."""
        response = test_client.get("/services/9999/schemas/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_schemas_by_service_custom_offset(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return empty items when offset is beyond total."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"offset": OFFSET_BEYOND_TOTAL},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 1
        assert data["offset"] == OFFSET_BEYOND_TOTAL

    def test_list_schemas_by_service_custom_limit(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return limited items while total remains unchanged."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"limit": 1},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["limit"] == 1

    def test_list_schemas_by_service_search_with_pagination(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return search-filtered total with pagination params."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"search": schema.name[:3], "limit": 1},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) <= 1

    def test_list_schemas_by_service_search_reports_filtered_total(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Filter rows by search and report the filtered total, not the page size."""
        for suffix in ("a", "b"):
            payload = SchemaWriteFactory.build(name=f"FilterMatchSchema_{suffix}")
            create_response = test_client.post(
                f"/services/{service.id}/schemas/",
                json=payload.model_dump(mode="json"),
            )
            assert create_response.status_code == status.HTTP_201_CREATED
        other = SchemaWriteFactory.build(name="UnrelatedSchema")
        test_client.post(
            f"/services/{service.id}/schemas/",
            json=other.model_dump(mode="json"),
        )

        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"search": "filtermatchschema", "limit": 1},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == LIST_QUERY_MATCH_TOTAL
        assert len(data["items"]) == 1

    @pytest.mark.asyncio
    async def test_list_schemas_by_service_deterministic_ordering_across_pages(
        self, test_client: TestClient, session: AsyncSession, service: Service
    ) -> None:
        """Sort equal created_at stably across pages via the id tie-breaker.

        Schema names are unique per service, so name ties cannot occur in this
        nested list; exercise the tie-breaker on created_at instead.
        """
        shared_created_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        created_ids: list[int] = []
        for name in ("tie_schema_a", "tie_schema_b"):
            row = await SchemaManager.create(
                session,
                SchemaWriteFactory.build(name=name),
                service_id=service.id,
            )
            row.created_at = shared_created_at
            session.add(row)
            await session.commit()
            await session.refresh(row)
            created_ids.append(row.id)
        created_ids.sort()

        first_page = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"sort": "created_at", "limit": 1, "offset": 0},
        )
        second_page = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"sort": "created_at", "limit": 1, "offset": 1},
        )
        assert first_page.status_code == status.HTTP_200_OK
        assert second_page.status_code == status.HTTP_200_OK
        assert first_page.json()["items"][0]["id"] == created_ids[0]
        assert second_page.json()["items"][0]["id"] == created_ids[1]

    def test_list_schemas_by_service_include_tables_with_pagination(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return paginated SchemaResponse with tables."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"include_tables": "true", "limit": 1},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert "tables" in data["items"][0]


class TestCreateSchemaForService:
    """Test POST /services/{service_id}/schemas/ endpoint."""

    def test_create_schema_for_service(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Create a schema for a service and return 201."""
        payload = SchemaWriteFactory.build()
        response = test_client.post(
            f"/services/{service.id}/schemas/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == payload.name

    def test_create_schema_for_service_duplicate_name(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return 409 when creating a schema with a duplicate name."""
        payload = SchemaWriteFactory.build()
        payload.name = schema.name
        response = test_client.post(
            f"/services/{service.id}/schemas/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_create_schema_for_service_not_found(self, test_client: TestClient) -> None:
        """Return 404 when creating a schema for a nonexistent service."""
        payload = SchemaWriteFactory.build()
        response = test_client.post(
            "/services/9999/schemas/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestRetrieveServiceSystemObservation:
    """Test GET /services/{service_id}/system-observation endpoint."""

    def test_retrieve_service_system_observation(
        self,
        test_client: TestClient,
        service: Service,
        service_observation: ServiceSystemObservation,
    ) -> None:
        """Return service observation with all fields for a service that has one."""
        response = test_client.get(f"/services/{service.id}/system-observation")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["service_id"] == service.id
        assert data["db_engine_version"] == service_observation.db_engine_version
        assert "observed_at" in data
        assert "id" in data

    def test_retrieve_service_system_observation_404_when_no_observation(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return 404 when service exists but no observation has been collected yet."""
        response = test_client.get(f"/services/{service.id}/system-observation")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_service_system_observation_404_when_service_not_found(
        self, test_client: TestClient
    ) -> None:
        """Return 404 when the service ID does not exist."""
        response = test_client.get("/services/99999/system-observation")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUpsertServiceSystemObservation:
    """Test PUT /services/{service_id}/system-observation endpoint."""

    def test_upsert_creates_new_observation(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Create a new observation when none exists and return 200."""
        payload = ServiceSystemObservationWriteFactory.build()
        response = test_client.put(
            f"/services/{service.id}/system-observation",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["service_id"] == service.id
        assert data["db_engine_version"] == payload.db_engine_version
        assert "id" in data

    def test_upsert_updates_existing_observation(
        self,
        test_client: TestClient,
        node: Node,
        service: Service,
        service_observation: ServiceSystemObservation,
    ) -> None:
        """Update existing observation in place and return 200 with updated fields."""
        test_client.post(
            f"/nodes/{node.id}/services/",
            json=ServiceWriteFactory.build().model_dump(mode="json"),
        )
        payload = ServiceSystemObservationWriteFactory.build(db_engine_version="8.4.0")
        response = test_client.put(
            f"/services/{service.id}/system-observation",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["db_engine_version"] == "8.4.0"
        assert response.json()["id"] == service_observation.id

    def test_upsert_idempotent_no_conflict_on_second_put(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return 200 on a repeat PUT with the same payload (no unique-constraint error)."""
        payload = ServiceSystemObservationWriteFactory.build()
        json_payload = payload.model_dump(mode="json")
        first = test_client.put(
            f"/services/{service.id}/system-observation", json=json_payload
        )
        assert first.status_code == status.HTTP_200_OK
        second = test_client.put(
            f"/services/{service.id}/system-observation", json=json_payload
        )
        assert second.status_code == status.HTTP_200_OK

    def test_upsert_preserves_same_id_across_updates(
        self,
        test_client: TestClient,
        service: Service,
        service_observation: ServiceSystemObservation,
    ) -> None:
        """Update an existing observation in place on PUT — same DB row, same id."""
        payload = ServiceSystemObservationWriteFactory.build(db_engine_version="5.7.44")
        response = test_client.put(
            f"/services/{service.id}/system-observation",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == service_observation.id

    def test_upsert_404_when_service_not_found(self, test_client: TestClient) -> None:
        """Return 404 when the service ID does not exist."""
        payload = ServiceSystemObservationWriteFactory.build()
        response = test_client.put(
            "/services/99999/system-observation",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_upsert_422_missing_observed_at(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return 422 when required field observed_at is absent."""
        data = ServiceSystemObservationWriteFactory.build().model_dump(mode="json")
        del data["observed_at"]
        response = test_client.put(
            f"/services/{service.id}/system-observation", json=data
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_upsert_422_missing_db_engine_version(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return 422 when required field db_engine_version is absent."""
        data = ServiceSystemObservationWriteFactory.build().model_dump(mode="json")
        del data["db_engine_version"]
        response = test_client.put(
            f"/services/{service.id}/system-observation", json=data
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
