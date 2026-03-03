"""Define tests for inventory node routes."""

from starlette import status
from starlette.testclient import TestClient


def test_list_nodes_empty(test_client: TestClient) -> None:
    """Return an empty list when no nodes exist."""
    response = test_client.get("/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []
