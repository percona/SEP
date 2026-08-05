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

"""Define tests for inventory node routes."""

from starlette import status
from starlette.testclient import TestClient

from app.core.pagination import DEFAULT_PAGINATION_LIMIT
from app.inventory.models import HostSystemObservation, Node, Service, SourceEnum
from tests.app.factories import (
    HostSystemObservationWriteFactory,
    NodeWriteFactory,
    ServiceWriteFactory,
)

CREATED_NODE_COUNT = 2
OFFSET_BEYOND_TOTAL = 999

# Pinned verbatim rather than imported from app.inventory.constants: the wording is
# part of the API contract, so an edit to the constant must fail the test.
UNCOLLECTED_NODE_DETAIL = "System observation not collected yet for this node"


class TestListNodes:
    """Test the GET /nodes/ endpoint."""

    def test_list_nodes_empty(self, test_client: TestClient) -> None:
        """Return an empty paginated response when no nodes exist."""
        response = test_client.get("/nodes/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["offset"] == 0
        assert data["limit"] == DEFAULT_PAGINATION_LIMIT

    def test_rejects_limit_zero(self, test_client: TestClient) -> None:
        """Return 422 when limit is zero."""
        response = test_client.get("/nodes/", params={"limit": 0})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_rejects_limit_above_cap(self, test_client: TestClient) -> None:
        """Return 422 when limit exceeds the global cap."""
        response = test_client.get("/nodes/", params={"limit": 201})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_rejects_negative_limit(self, test_client: TestClient) -> None:
        """Return 422 when limit is negative."""
        response = test_client.get("/nodes/", params={"limit": -1})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_list_nodes_multiple(self, test_client: TestClient) -> None:
        """Return a list of nodes with services loaded."""
        payload1 = NodeWriteFactory.build()
        payload2 = NodeWriteFactory.build()
        test_client.post("/nodes/", json=payload1.model_dump(mode="json"))
        test_client.post("/nodes/", json=payload2.model_dump(mode="json"))

        response = test_client.get("/nodes/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == CREATED_NODE_COUNT
        assert data["total"] == CREATED_NODE_COUNT
        assert "services" in data["items"][0]

    def test_list_nodes_filter_by_source(self, test_client: TestClient) -> None:
        """Return only nodes matching the given source filter."""
        pmm_payload = NodeWriteFactory.build(
            source=SourceEnum.PMM, external_id="pmm-node"
        )
        plain_payload = NodeWriteFactory.build()
        test_client.post("/nodes/", json=pmm_payload.model_dump(mode="json"))
        test_client.post("/nodes/", json=plain_payload.model_dump(mode="json"))

        response = test_client.get("/nodes/", params={"source": "pmm"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["source"] == "pmm"

    def test_list_nodes_filter_by_external_id(self, test_client: TestClient) -> None:
        """Return only nodes matching the given external_id filter."""
        matching = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="abc")
        other = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="xyz")
        test_client.post("/nodes/", json=matching.model_dump(mode="json"))
        test_client.post("/nodes/", json=other.model_dump(mode="json"))

        response = test_client.get("/nodes/", params={"external_id": "abc"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["external_id"] == "abc"

    def test_list_nodes_filter_by_node_type(self, test_client: TestClient) -> None:
        """Return only nodes matching the given node_type filter."""
        generic = NodeWriteFactory.build(type="generic")
        remote = NodeWriteFactory.build(type="remote")
        test_client.post("/nodes/", json=generic.model_dump(mode="json"))
        test_client.post("/nodes/", json=remote.model_dump(mode="json"))

        response = test_client.get("/nodes/", params={"node_type": "generic"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["type"] == "generic"

    def test_list_nodes_custom_offset(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return empty items when offset is beyond total."""
        response = test_client.get("/nodes/", params={"offset": OFFSET_BEYOND_TOTAL})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 1
        assert data["offset"] == OFFSET_BEYOND_TOTAL

    def test_list_nodes_custom_limit(self, test_client: TestClient, node: Node) -> None:
        """Return limited items while total remains unchanged."""
        response = test_client.get("/nodes/", params={"limit": 1})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["limit"] == 1

    def test_list_nodes_filter_with_pagination(
        self,
        test_client: TestClient,
    ) -> None:
        """Return filtered total with pagination params."""
        generic = NodeWriteFactory.build(type="generic")
        remote = NodeWriteFactory.build(type="remote")
        test_client.post("/nodes/", json=generic.model_dump(mode="json"))
        test_client.post("/nodes/", json=remote.model_dump(mode="json"))

        response = test_client.get(
            "/nodes/", params={"node_type": "generic", "limit": 1}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1


class TestRetrieveNode:
    """Test the GET /nodes/{node_id} endpoint."""

    def test_retrieve_node(self, test_client: TestClient, node: Node) -> None:
        """Return a node with its services list."""
        response = test_client.get(f"/nodes/{node.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == node.id
        assert "services" in data

    def test_retrieve_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        response = test_client.get("/nodes/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestCreateNode:
    """Test the POST /nodes/ endpoint."""

    def test_create_node(self, test_client: TestClient) -> None:
        """Create a node and return 201 with the new ID."""
        payload = NodeWriteFactory.build()
        response = test_client.post("/nodes/", json=payload.model_dump(mode="json"))
        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.json()

    def test_create_node_with_source(self, test_client: TestClient) -> None:
        """Create a node with source and external_id."""
        payload = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="ext-123")
        response = test_client.post("/nodes/", json=payload.model_dump(mode="json"))
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["source"] == "pmm"
        assert data["external_id"] == "ext-123"

    def test_create_node_duplicate_external_id_source(
        self, test_client: TestClient
    ) -> None:
        """Return 409 when creating a node with duplicate (external_id, source)."""
        payload = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="dup-ext")
        response = test_client.post("/nodes/", json=payload.model_dump(mode="json"))
        assert response.status_code == status.HTTP_201_CREATED

        payload2 = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="dup-ext")
        response2 = test_client.post("/nodes/", json=payload2.model_dump(mode="json"))
        assert response2.status_code == status.HTTP_409_CONFLICT

    def test_create_node_external_id_without_source(
        self, test_client: TestClient
    ) -> None:
        """Return 422 when external_id is set but source is None."""
        payload = NodeWriteFactory.build()
        data = payload.model_dump(mode="json")
        data["external_id"] = "some-id"
        data["source"] = None
        response = test_client.post("/nodes/", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestUpdateNode:
    """Test the PUT /nodes/{node_id} endpoint."""

    def test_update_node(self, test_client: TestClient, node: Node) -> None:
        """Update a node name and return 200."""
        payload = NodeWriteFactory.build(name="updated-name")
        response = test_client.put(
            f"/nodes/{node.id}", json=payload.model_dump(mode="json")
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "updated-name"

    def test_update_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        payload = NodeWriteFactory.build()
        response = test_client.put("/nodes/99999", json=payload.model_dump(mode="json"))
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteNode:
    """Test the DELETE /nodes/{node_id} endpoint."""

    def test_delete_node(self, test_client: TestClient, node: Node) -> None:
        """Delete a node and confirm it is gone."""
        response = test_client.delete(f"/nodes/{node.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        response = test_client.get(f"/nodes/{node.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        response = test_client.delete("/nodes/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestListServicesByNode:
    """Test the GET /nodes/{node_id}/services/ endpoint."""

    def test_list_services_by_node_empty(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return an empty paginated response when the node has no services."""
        response = test_client.get(f"/nodes/{node.id}/services/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["offset"] == 0
        assert data["limit"] == DEFAULT_PAGINATION_LIMIT

    def test_list_services_by_node(
        self, test_client: TestClient, node: Node, service: Service
    ) -> None:
        """Return services with schemas loaded for a node."""
        response = test_client.get(f"/nodes/{node.id}/services/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["id"] == service.id
        assert "schemas" in data["items"][0]

    def test_list_services_by_node_filter_service_type(
        self, test_client: TestClient, node: Node, service: Service
    ) -> None:
        """Return only services matching the given service_type filter."""
        response = test_client.get(
            f"/nodes/{node.id}/services/",
            params={"service_type": service.type.value},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == service.id

    def test_list_services_by_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        response = test_client.get("/nodes/99999/services/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_services_by_node_custom_offset(
        self, test_client: TestClient, node: Node, service: Service
    ) -> None:
        """Return empty items when offset is beyond total."""
        response = test_client.get(
            f"/nodes/{node.id}/services/", params={"offset": OFFSET_BEYOND_TOTAL}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 1
        assert data["offset"] == OFFSET_BEYOND_TOTAL

    def test_list_services_by_node_custom_limit(
        self, test_client: TestClient, node: Node, service: Service
    ) -> None:
        """Return limited items while total remains unchanged."""
        response = test_client.get(f"/nodes/{node.id}/services/", params={"limit": 1})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["limit"] == 1


class TestCreateServiceForNode:
    """Test the POST /nodes/{node_id}/services/ endpoint."""

    def test_create_service_for_node(self, test_client: TestClient, node: Node) -> None:
        """Create a service for a node and return 201."""
        payload = ServiceWriteFactory.build()
        response = test_client.post(
            f"/nodes/{node.id}/services/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["node_id"] == node.id

    def test_create_service_for_node_external_id_without_node_source(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return 400 when service has external_id but node has no source."""
        payload = ServiceWriteFactory.build(external_id="svc-ext-123")
        response = test_client.post(
            f"/nodes/{node.id}/services/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_service_for_node_duplicate_external_id(
        self, test_client: TestClient
    ) -> None:
        """Return 409 when creating a service with duplicate (external_id, node_id)."""
        node_payload = NodeWriteFactory.build(
            source=SourceEnum.PMM, external_id="node-ext"
        )
        node_resp = test_client.post(
            "/nodes/", json=node_payload.model_dump(mode="json")
        )
        node_id = node_resp.json()["id"]

        svc_payload = ServiceWriteFactory.build(external_id="svc-dup")
        response = test_client.post(
            f"/nodes/{node_id}/services/",
            json=svc_payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_201_CREATED

        svc_payload2 = ServiceWriteFactory.build(external_id="svc-dup")
        response2 = test_client.post(
            f"/nodes/{node_id}/services/",
            json=svc_payload2.model_dump(mode="json"),
        )
        assert response2.status_code == status.HTTP_409_CONFLICT

    def test_create_service_for_node_duplicate_port(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return 409 when creating a service with duplicate (port, node_id)."""
        svc_payload = ServiceWriteFactory.build(port=3306)
        response = test_client.post(
            f"/nodes/{node.id}/services/",
            json=svc_payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_201_CREATED

        svc_payload2 = ServiceWriteFactory.build(port=3306)
        response2 = test_client.post(
            f"/nodes/{node.id}/services/",
            json=svc_payload2.model_dump(mode="json"),
        )
        assert response2.status_code == status.HTTP_409_CONFLICT

    def test_create_service_for_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        payload = ServiceWriteFactory.build()
        response = test_client.post(
            "/nodes/99999/services/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestRetrieveHostSystemObservation:
    """Test GET /nodes/{node_id}/system-observation endpoint."""

    def test_retrieve_host_system_observation(
        self,
        test_client: TestClient,
        node: Node,
        host_observation: HostSystemObservation,
    ) -> None:
        """Return host observation with all fields for a node that has one."""
        response = test_client.get(f"/nodes/{node.id}/system-observation")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["node_id"] == node.id
        assert data["os_version"] == host_observation.os_version
        assert "observed_at" in data
        assert "id" in data

    def test_retrieve_host_system_observation_404_when_no_observation(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return 404 with the uncollected detail when the node has no observation."""
        response = test_client.get(f"/nodes/{node.id}/system-observation")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == UNCOLLECTED_NODE_DETAIL

    def test_retrieve_host_system_observation_404_when_node_not_found(
        self, test_client: TestClient
    ) -> None:
        """Return 404 with the default detail when the node ID does not exist."""
        response = test_client.get("/nodes/99999/system-observation")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Not Found"

    def test_retrieve_host_system_observation_404_for_another_nodes_observation(
        self,
        test_client: TestClient,
        node: Node,
        host_observation: HostSystemObservation,
    ) -> None:
        """Keep one node's observation from surfacing when reading a sibling node."""
        other = test_client.post(
            "/nodes/", json=NodeWriteFactory.build().model_dump(mode="json")
        )
        assert other.status_code == status.HTTP_201_CREATED
        other_node_id = other.json()["id"]
        assert other_node_id != node.id

        response = test_client.get(f"/nodes/{other_node_id}/system-observation")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == UNCOLLECTED_NODE_DETAIL

    def test_retrieve_host_system_observation_after_upsert_returns_200(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Leave the uncollected state once the syncer writes an observation.

        The uncollected 404 must be a transient state, not a sticky one: the same
        GET that reported it has to answer 200 after a PUT lands.
        """
        before = test_client.get(f"/nodes/{node.id}/system-observation")
        assert before.status_code == status.HTTP_404_NOT_FOUND
        assert before.json()["detail"] == UNCOLLECTED_NODE_DETAIL

        payload = HostSystemObservationWriteFactory.build()
        upsert = test_client.put(
            f"/nodes/{node.id}/system-observation",
            json=payload.model_dump(mode="json"),
        )
        assert upsert.status_code == status.HTTP_200_OK

        after = test_client.get(f"/nodes/{node.id}/system-observation")
        assert after.status_code == status.HTTP_200_OK
        assert after.json()["node_id"] == node.id
        assert after.json()["os_version"] == payload.os_version


class TestUpsertHostSystemObservation:
    """Test PUT /nodes/{node_id}/system-observation endpoint."""

    def test_upsert_creates_new_observation(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Create a new observation when none exists and return 200."""
        payload = HostSystemObservationWriteFactory.build()
        response = test_client.put(
            f"/nodes/{node.id}/system-observation",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["node_id"] == node.id
        assert data["os_version"] == payload.os_version
        assert "id" in data

    def test_upsert_updates_existing_observation(
        self,
        test_client: TestClient,
        node: Node,
        host_observation: HostSystemObservation,
    ) -> None:
        """Update existing observation in place and return 200 with updated fields."""
        test_client.post(
            "/nodes/", json=NodeWriteFactory.build().model_dump(mode="json")
        )
        payload = HostSystemObservationWriteFactory.build(os_version="Debian 12")
        response = test_client.put(
            f"/nodes/{node.id}/system-observation",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["os_version"] == "Debian 12"
        assert response.json()["id"] == host_observation.id

    def test_upsert_idempotent_no_conflict_on_second_put(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return 200 on a repeat PUT with the same payload (no unique-constraint error)."""
        payload = HostSystemObservationWriteFactory.build()
        json_payload = payload.model_dump(mode="json")
        first = test_client.put(
            f"/nodes/{node.id}/system-observation", json=json_payload
        )
        assert first.status_code == status.HTTP_200_OK
        second = test_client.put(
            f"/nodes/{node.id}/system-observation", json=json_payload
        )
        assert second.status_code == status.HTTP_200_OK

    def test_upsert_preserves_same_id_across_updates(
        self,
        test_client: TestClient,
        node: Node,
        host_observation: HostSystemObservation,
    ) -> None:
        """Update an existing observation in place on PUT — same DB row, same id."""
        payload = HostSystemObservationWriteFactory.build(os_version="Rocky Linux 9")
        response = test_client.put(
            f"/nodes/{node.id}/system-observation",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == host_observation.id

    def test_upsert_404_when_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 when the node ID does not exist."""
        payload = HostSystemObservationWriteFactory.build()
        response = test_client.put(
            "/nodes/99999/system-observation",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_upsert_422_missing_observed_at(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return 422 when required field observed_at is absent."""
        data = HostSystemObservationWriteFactory.build().model_dump(mode="json")
        del data["observed_at"]
        response = test_client.put(f"/nodes/{node.id}/system-observation", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_upsert_422_when_all_observation_fields_are_none(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return 422 when os_version, installed_packages, and config are all None."""
        base = HostSystemObservationWriteFactory.build()
        data = base.model_dump(mode="json")
        data["os_version"] = None
        data["installed_packages"] = None
        data["config"] = None
        response = test_client.put(f"/nodes/{node.id}/system-observation", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
