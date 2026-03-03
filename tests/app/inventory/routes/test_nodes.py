"""Define tests for inventory node routes."""

from starlette import status
from starlette.testclient import TestClient

from app.inventory.models import Node, Service, SourceEnum
from tests.app.factories import NodeWriteFactory, ServiceWriteFactory

CREATED_NODE_COUNT = 2


class TestListNodes:
    """Test the GET / endpoint."""

    def test_list_nodes_empty(self, test_client: TestClient) -> None:
        """Return an empty list when no nodes exist."""
        response = test_client.get("/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_nodes_multiple(self, test_client: TestClient) -> None:
        """Return a list of nodes with services loaded."""
        payload1 = NodeWriteFactory.build()
        payload2 = NodeWriteFactory.build()
        test_client.post("/", json=payload1.model_dump(mode="json"))
        test_client.post("/", json=payload2.model_dump(mode="json"))

        response = test_client.get("/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == CREATED_NODE_COUNT
        assert "services" in data[0]

    def test_list_nodes_filter_by_source(self, test_client: TestClient) -> None:
        """Return only nodes matching the given source filter."""
        pmm_payload = NodeWriteFactory.build(
            source=SourceEnum.PMM, external_id="pmm-node"
        )
        plain_payload = NodeWriteFactory.build()
        test_client.post("/", json=pmm_payload.model_dump(mode="json"))
        test_client.post("/", json=plain_payload.model_dump(mode="json"))

        response = test_client.get("/", params={"source": "pmm"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["source"] == "pmm"

    def test_list_nodes_filter_by_external_id(self, test_client: TestClient) -> None:
        """Return only nodes matching the given external_id filter."""
        matching = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="abc")
        other = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="xyz")
        test_client.post("/", json=matching.model_dump(mode="json"))
        test_client.post("/", json=other.model_dump(mode="json"))

        response = test_client.get("/", params={"external_id": "abc"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["external_id"] == "abc"

    def test_list_nodes_filter_by_node_type(self, test_client: TestClient) -> None:
        """Return only nodes matching the given node_type filter."""
        generic = NodeWriteFactory.build(type="generic")
        remote = NodeWriteFactory.build(type="remote")
        test_client.post("/", json=generic.model_dump(mode="json"))
        test_client.post("/", json=remote.model_dump(mode="json"))

        response = test_client.get("/", params={"node_type": "generic"})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["type"] == "generic"


class TestRetrieveNode:
    """Test the GET /{node_id} endpoint."""

    def test_retrieve_node(self, test_client: TestClient, node: Node) -> None:
        """Return a node with its services list."""
        response = test_client.get(f"/{node.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == node.id
        assert "services" in data

    def test_retrieve_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        response = test_client.get("/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestCreateNode:
    """Test the POST / endpoint."""

    def test_create_node(self, test_client: TestClient) -> None:
        """Create a node and return 201 with the new ID."""
        payload = NodeWriteFactory.build()
        response = test_client.post("/", json=payload.model_dump(mode="json"))
        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.json()

    def test_create_node_with_source(self, test_client: TestClient) -> None:
        """Create a node with source and external_id."""
        payload = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="ext-123")
        response = test_client.post("/", json=payload.model_dump(mode="json"))
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["source"] == "pmm"
        assert data["external_id"] == "ext-123"

    def test_create_node_duplicate_external_id_source(
        self, test_client: TestClient
    ) -> None:
        """Return 409 when creating a node with duplicate (external_id, source)."""
        payload = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="dup-ext")
        response = test_client.post("/", json=payload.model_dump(mode="json"))
        assert response.status_code == status.HTTP_201_CREATED

        payload2 = NodeWriteFactory.build(source=SourceEnum.PMM, external_id="dup-ext")
        response2 = test_client.post("/", json=payload2.model_dump(mode="json"))
        assert response2.status_code == status.HTTP_409_CONFLICT

    def test_create_node_external_id_without_source(
        self, test_client: TestClient
    ) -> None:
        """Return 422 when external_id is set but source is None."""
        payload = NodeWriteFactory.build()
        data = payload.model_dump(mode="json")
        data["external_id"] = "some-id"
        data["source"] = None
        response = test_client.post("/", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestUpdateNode:
    """Test the PUT /{node_id} endpoint."""

    def test_update_node(self, test_client: TestClient, node: Node) -> None:
        """Update a node name and return 200."""
        payload = NodeWriteFactory.build(name="updated-name")
        response = test_client.put(f"/{node.id}", json=payload.model_dump(mode="json"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "updated-name"

    def test_update_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        payload = NodeWriteFactory.build()
        response = test_client.put("/99999", json=payload.model_dump(mode="json"))
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteNode:
    """Test the DELETE /{node_id} endpoint."""

    def test_delete_node(self, test_client: TestClient, node: Node) -> None:
        """Delete a node and confirm it is gone."""
        response = test_client.delete(f"/{node.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        response = test_client.get(f"/{node.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        response = test_client.delete("/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestListServicesByNode:
    """Test the GET /{node_id}/services/ endpoint."""

    def test_list_services_by_node_empty(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return an empty list when the node has no services."""
        response = test_client.get(f"/{node.id}/services/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_services_by_node(
        self, test_client: TestClient, node: Node, service: Service
    ) -> None:
        """Return services with schemas loaded for a node."""
        response = test_client.get(f"/{node.id}/services/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == service.id
        assert "schemas" in data[0]

    def test_list_services_by_node_filter_service_type(
        self, test_client: TestClient, node: Node, service: Service
    ) -> None:
        """Return only services matching the given service_type filter."""
        response = test_client.get(
            f"/{node.id}/services/",
            params={"service_type": service.type.value},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == service.id

    def test_list_services_by_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        response = test_client.get("/99999/services/")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestCreateServiceForNode:
    """Test the POST /{node_id}/services/ endpoint."""

    def test_create_service_for_node(self, test_client: TestClient, node: Node) -> None:
        """Create a service for a node and return 201."""
        payload = ServiceWriteFactory.build()
        response = test_client.post(
            f"/{node.id}/services/",
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
            f"/{node.id}/services/",
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
        node_resp = test_client.post("/", json=node_payload.model_dump(mode="json"))
        node_id = node_resp.json()["id"]

        svc_payload = ServiceWriteFactory.build(external_id="svc-dup")
        response = test_client.post(
            f"/{node_id}/services/",
            json=svc_payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_201_CREATED

        svc_payload2 = ServiceWriteFactory.build(external_id="svc-dup")
        response2 = test_client.post(
            f"/{node_id}/services/",
            json=svc_payload2.model_dump(mode="json"),
        )
        assert response2.status_code == status.HTTP_409_CONFLICT

    def test_create_service_for_node_duplicate_port(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return 409 when creating a service with duplicate (port, node_id)."""
        svc_payload = ServiceWriteFactory.build(port=3306)
        response = test_client.post(
            f"/{node.id}/services/",
            json=svc_payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_201_CREATED

        svc_payload2 = ServiceWriteFactory.build(port=3306)
        response2 = test_client.post(
            f"/{node.id}/services/",
            json=svc_payload2.model_dump(mode="json"),
        )
        assert response2.status_code == status.HTTP_409_CONFLICT

    def test_create_service_for_node_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent node ID."""
        payload = ServiceWriteFactory.build()
        response = test_client.post(
            "/99999/services/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
