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

"""Define tests for the inventory identity-link routes."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.testclient import TestClient

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.pagination import DEFAULT_PAGINATION_LIMIT
from app.inventory.crud import NodeManager
from app.inventory.models import IdentityLinkDecisionEnum, Node, Service
from tests.app.factories import NodeWriteFactory
from tests.app.inventory.conftest import retire_in_place

#: A confirmation appends three records, two of which name the predecessor:
#: the binding it closed on its own identifier, and the one it opened on the
#: transferred identifier. The third names the successor.
PREDECESSOR_ALIAS_COUNT = 2


def confirm(client: TestClient, path: str, successor_id: int) -> None:
    """Confirm a pairing over real HTTP and assert the route accepted it."""
    response = client.post(
        path,
        json={
            "successor_id": successor_id,
            "decision": IdentityLinkDecisionEnum.CONFIRMED,
        },
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT


class TestListNodeIdentityCandidates:
    """Test the GET /nodes/identity-candidates endpoint."""

    def test_an_empty_estate_returns_an_empty_page(
        self, test_client: TestClient
    ) -> None:
        """Answer 200 with an empty page rather than 404 when nothing was split."""
        response = test_client.get("/nodes/identity-candidates")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": DEFAULT_PAGINATION_LIMIT,
        }

    @pytest.mark.asyncio
    async def test_a_split_pair_is_served_with_both_rows_in_full(
        self, test_client: TestClient, session: AsyncSession, node: Node
    ) -> None:
        """Serve enough of both rows for an operator to judge the pairing.

        The route is a distinct path operation from ``GET /{node_id}``, and it is
        declared above it — a 200 here is what proves the parameterized route did
        not claim the path and answer 422.
        """
        successor = await NodeManager.create(
            session, NodeWriteFactory.build(name=node.name, address="10.9.9.9")
        )

        response = test_client.get("/nodes/identity-candidates")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        candidate = body["items"][0]
        assert candidate["predecessor"]["id"] == node.id
        assert candidate["successor"]["id"] == successor.id
        assert candidate["matched_on"] == ["name"]
        assert candidate["predecessor"]["created_at"]
        assert candidate["predecessor"]["retired_at"] is None


class TestDecideNodeIdentityLink:
    """Test the POST /nodes/{node_id}/identity-link endpoint."""

    @pytest.mark.asyncio
    async def test_a_confirmation_transfers_the_identity(
        self,
        test_client: TestClient,
        session: AsyncSession,
        split_nodes: tuple[Node, Node],
    ) -> None:
        """Answer 204 and leave the predecessor holding the successor's identifier."""
        predecessor, successor = split_nodes
        transferred = successor.external_id

        confirm(test_client, f"/nodes/{predecessor.id}/identity-link", successor.id)

        await session.refresh(predecessor)
        await session.refresh(successor)
        assert predecessor.external_id == transferred
        assert predecessor.retired_at is None
        assert successor.retired_at is not None

    @pytest.mark.asyncio
    async def test_a_rejection_is_accepted(
        self, test_client: TestClient, split_nodes: tuple[Node, Node]
    ) -> None:
        """Answer 204 on a rejection and stop offering the pairing."""
        predecessor, successor = split_nodes

        response = test_client.post(
            f"/nodes/{predecessor.id}/identity-link",
            json={
                "successor_id": successor.id,
                "decision": IdentityLinkDecisionEnum.REJECTED,
            },
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert test_client.get("/nodes/identity-candidates").json()["total"] == 0

    @pytest.mark.asyncio
    async def test_a_reversal_is_accepted(
        self,
        test_client: TestClient,
        session: AsyncSession,
        split_nodes: tuple[Node, Node],
    ) -> None:
        """Answer 204 on a reversal and give each row its own identifier back."""
        predecessor, successor = split_nodes
        own_identifier = predecessor.external_id
        confirm(test_client, f"/nodes/{predecessor.id}/identity-link", successor.id)

        response = test_client.post(
            f"/nodes/{predecessor.id}/identity-link",
            json={
                "successor_id": successor.id,
                "decision": IdentityLinkDecisionEnum.UNLINKED,
            },
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        await session.refresh(predecessor)
        assert predecessor.external_id == own_identifier

    @pytest.mark.asyncio
    async def test_a_tombstoned_predecessor_is_addressable(
        self,
        test_client: TestClient,
        session: AsyncSession,
        tombstoned_split_nodes: tuple[Node, Node],
    ) -> None:
        """Resolve a retired predecessor from the path rather than answering 404."""
        predecessor, successor = tombstoned_split_nodes

        confirm(test_client, f"/nodes/{predecessor.id}/identity-link", successor.id)

        await session.refresh(predecessor)
        assert predecessor.retired_at is None

    def test_an_unknown_successor_is_not_found(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Answer 404 when the body names a row that does not exist."""
        assert node.id is not None
        response = test_client.post(
            f"/nodes/{node.id}/identity-link",
            json={
                "successor_id": node.id + 1000,
                "decision": IdentityLinkDecisionEnum.CONFIRMED,
            },
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_a_second_confirmation_conflicts(
        self, test_client: TestClient, split_nodes: tuple[Node, Node]
    ) -> None:
        """Answer 409 rather than logging one confirmation twice."""
        predecessor, successor = split_nodes
        confirm(test_client, f"/nodes/{predecessor.id}/identity-link", successor.id)

        response = test_client.post(
            f"/nodes/{predecessor.id}/identity-link",
            json={
                "successor_id": successor.id,
                "decision": IdentityLinkDecisionEnum.CONFIRMED,
            },
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_an_unknown_decision_is_rejected_at_the_boundary(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Answer 422 on a decision outside the enum, the body model being real."""
        assert node.id is not None
        response = test_client.post(
            f"/nodes/{node.id}/identity-link",
            json={"successor_id": node.id + 1, "decision": "deleted"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestListNodeIdentityAliases:
    """Test the GET /nodes/{node_id}/identity-aliases endpoint."""

    def test_a_node_with_no_history_returns_an_empty_page(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Answer 200 with an empty page rather than 404 for an untouched node."""
        response = test_client.get(f"/nodes/{node.id}/identity-aliases")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []
        assert response.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_a_confirmation_is_served_oldest_first(
        self, test_client: TestClient, split_nodes: tuple[Node, Node]
    ) -> None:
        """Serve the predecessor's binding records in the order they were written."""
        predecessor, successor = split_nodes
        superseded = predecessor.external_id
        transferred = successor.external_id
        confirm(test_client, f"/nodes/{predecessor.id}/identity-link", successor.id)

        response = test_client.get(f"/nodes/{predecessor.id}/identity-aliases")

        assert response.status_code == status.HTTP_200_OK
        records = response.json()["items"]
        assert [record["external_id"] for record in records] == [
            superseded,
            transferred,
        ]
        assert records[0]["valid_to"] is not None
        assert records[1]["valid_to"] is None

    @pytest.mark.asyncio
    async def test_a_retired_node_is_addressable(
        self, test_client: TestClient, session: AsyncSession, node: Node
    ) -> None:
        """Answer 200 for a tombstone, the route resolving retired-inclusive."""
        await retire_in_place(session, node)

        response = test_client.get(f"/nodes/{node.id}/identity-aliases")

        assert response.status_code == status.HTTP_200_OK


class TestNodeExternalIdResolution:
    """Test that GET /nodes/ resolves a superseded identifier through the alias."""

    @pytest.mark.asyncio
    async def test_a_superseded_identifier_finds_the_surviving_row(
        self, test_client: TestClient, split_nodes: tuple[Node, Node]
    ) -> None:
        """Keep a reference persisted before the re-registration resolving."""
        predecessor, successor = split_nodes
        superseded = predecessor.external_id
        confirm(test_client, f"/nodes/{predecessor.id}/identity-link", successor.id)

        response = test_client.get(f"/nodes/?external_id={superseded}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == predecessor.id

    def test_an_identifier_with_no_history_keeps_column_equality(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Leave the overwhelming majority of lookups exactly as they were."""
        response = test_client.get(f"/nodes/?external_id={node.external_id}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == node.id

    @pytest.mark.asyncio
    async def test_an_identifier_whose_row_was_collected_returns_an_empty_page(
        self,
        test_client: TestClient,
        session: AsyncSession,
        split_nodes: tuple[Node, Node],
    ) -> None:
        """Answer 200 with nothing when the alias names a row that is gone.

        The alias record deliberately carries no foreign key, so collection can
        leave one naming a deleted row — that has to read as "no match", never as
        a 500.
        """
        predecessor, successor = split_nodes
        superseded = predecessor.external_id
        confirm(test_client, f"/nodes/{predecessor.id}/identity-link", successor.id)
        await session.delete(predecessor)
        await session.commit()

        response = test_client.get(f"/nodes/?external_id={superseded}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 0


class TestServiceIdentityRoutes:
    """Test the service-side identity routes.

    Routing is resolved per endpoint, so the node routes' 200 proves nothing
    about these — each needs its own assertion.
    """

    def test_an_empty_estate_returns_an_empty_candidate_page(
        self, test_client: TestClient
    ) -> None:
        """Answer 200 on the collection-level static path, not 422."""
        response = test_client.get("/services/identity-candidates")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_a_same_node_split_is_served(
        self, test_client: TestClient, split_services: tuple[Service, Service]
    ) -> None:
        """Serve the pairing two same-name services on one node make."""
        predecessor, successor = split_services

        response = test_client.get("/services/identity-candidates")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["predecessor"]["id"] == predecessor.id
        assert body["items"][0]["successor"]["id"] == successor.id

    @pytest.mark.asyncio
    async def test_a_confirmation_transfers_the_identity(
        self,
        test_client: TestClient,
        session: AsyncSession,
        split_services: tuple[Service, Service],
    ) -> None:
        """Answer 204 and move the identifier onto the surviving service."""
        predecessor, successor = split_services
        transferred = successor.external_id

        confirm(test_client, f"/services/{predecessor.id}/identity-link", successor.id)

        await session.refresh(predecessor)
        assert predecessor.external_id == transferred

    @pytest.mark.asyncio
    async def test_the_alias_list_is_served(
        self, test_client: TestClient, split_services: tuple[Service, Service]
    ) -> None:
        """Serve a confirmed service's binding records."""
        predecessor, successor = split_services
        confirm(test_client, f"/services/{predecessor.id}/identity-link", successor.id)

        response = test_client.get(f"/services/{predecessor.id}/identity-aliases")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["items"]) == PREDECESSOR_ALIAS_COUNT

    @pytest.mark.asyncio
    async def test_a_superseded_identifier_finds_the_surviving_service(
        self, test_client: TestClient, split_services: tuple[Service, Service]
    ) -> None:
        """Resolve a superseded service identifier through the new query parameter."""
        predecessor, successor = split_services
        superseded = predecessor.external_id
        confirm(test_client, f"/services/{predecessor.id}/identity-link", successor.id)

        response = test_client.get(f"/services/?external_id={superseded}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == predecessor.id

    @pytest.mark.asyncio
    async def test_omitting_the_new_filter_leaves_the_listing_unchanged(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Keep every existing caller of GET /services/ working untouched."""
        response = test_client.get("/services/")

        assert response.status_code == status.HTTP_200_OK
        assert [item["id"] for item in response.json()["items"]] == [service.id]

    @pytest.mark.asyncio
    async def test_a_node_confirmation_surfaces_the_service_pairing_over_http(
        self,
        test_client: TestClient,
        split_nodes_with_services: tuple[Node, Node, Service, Service],
    ) -> None:
        """Surface the implied service pairing once its nodes are linked."""
        predecessor_node, successor_node, predecessor, successor = (
            split_nodes_with_services
        )
        assert test_client.get("/services/identity-candidates").json()["total"] == 0

        confirm(
            test_client,
            f"/nodes/{predecessor_node.id}/identity-link",
            successor_node.id,
        )

        body = test_client.get("/services/identity-candidates").json()
        assert body["total"] == 1
        assert body["items"][0]["predecessor"]["id"] == predecessor.id
        assert body["items"][0]["successor"]["id"] == successor.id


class TestIdentityRoutesAreNotServicePrincipalOnly:
    """Test that a human operator reaches the identity routes.

    An identity link is an operator judgement rather than a row the syncer owns,
    so these routes are the deliberate exclusion from the service-principal
    restriction the node and service writes carry. The fixture client
    authenticates as an ordinary user, which those writes refuse.
    """

    @pytest.mark.asyncio
    async def test_a_human_caller_may_decide_a_node_link(
        self, test_client: TestClient, split_nodes: tuple[Node, Node]
    ) -> None:
        """Admit a non-principal caller on the node decision route."""
        predecessor, successor = split_nodes

        response = test_client.post(
            f"/nodes/{predecessor.id}/identity-link",
            json={
                "successor_id": successor.id,
                "decision": IdentityLinkDecisionEnum.REJECTED,
            },
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.asyncio
    async def test_a_human_caller_may_decide_a_service_link(
        self, test_client: TestClient, split_services: tuple[Service, Service]
    ) -> None:
        """Admit a non-principal caller on the service decision route."""
        predecessor, successor = split_services

        response = test_client.post(
            f"/services/{predecessor.id}/identity-link",
            json={
                "successor_id": successor.id,
                "decision": IdentityLinkDecisionEnum.REJECTED,
            },
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.asyncio
    async def test_the_deciding_caller_is_recorded_on_the_records(
        self,
        test_client: TestClient,
        session: AsyncSession,
        regular_user: CasdoorUser,
        node: Node,
    ) -> None:
        """Record who decided, an audit trail without a principal being no trail."""
        successor = await NodeManager.create(
            session, NodeWriteFactory.build(name=node.name)
        )
        confirm(test_client, f"/nodes/{node.id}/identity-link", successor.id)

        records = test_client.get(f"/nodes/{node.id}/identity-aliases").json()["items"]

        assert {record["principal"] for record in records} == {str(regular_user.id)}
