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

"""Cover the SEP-owned task-history actor types and their resolvers."""

from typing import Any

import pytest

from app.api.deps import SERVICE_PRINCIPAL_ID
from app.core.pagination import PaginatedResponse, Pagination
from app.sep.api.task_history_actors import (
    resolve_actor,
    resolve_history_payload_actors,
    resolve_task_actors,
    resolve_task_history_actors,
    SepTaskHistoryResponse,
    SepTaskResponse,
    SYSTEM_ACTOR_LABELS,
)
from app.tasks.crud import SYSTEM_EXECUTOR_IDS
from app.tasks.models import SYSTEM_USER, TaskBackendEnum
from tests.app.factories import TaskFactory

CREATOR_ID = "11111111-1111-4111-8111-111111111111"
UPDATER_ID = "22222222-2222-4222-8222-222222222222"
EXECUTOR_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_ID = "99999999-9999-4999-8999-999999999999"

USERNAME_MAP = {
    CREATOR_ID: "alice",
    UPDATER_ID: "bob",
    EXECUTOR_ID: "carol",
}


def _task_payload(**overrides: Any) -> dict[str, Any]:
    """Build a JSON-mode task payload with the supplied field overrides."""
    task = TaskFactory.build(
        id=1, name="backup", owner="BACKUP_MONGO", backend=TaskBackendEnum.PROXY
    )
    payload = task.model_dump(mode="json")
    payload["data"] = {
        "task": "run-python",
        "meta": {"target": "host1"},
        "payload": "file:///plugins/backup_mongo/pbm_config_payload",
    }
    payload["deleted_at"] = None
    payload["created_by"] = CREATOR_ID
    payload["last_updated_by"] = UPDATER_ID
    payload.update(overrides)
    return payload


def _history_payload(**overrides: Any) -> dict[str, Any]:
    """Build a JSON-mode task-history row with the supplied field overrides."""
    payload = {
        "id": 1,
        "status": "success",
        "started_at": "2026-01-01T10:00:00+00:00",
        "execution_request": {"task": "backup", "target": "host1"},
        "executed_by": EXECUTOR_ID,
        "task": _task_payload(),
    }
    payload.update(overrides)
    return payload


class TestResolveActor:
    """Cover the single-identifier resolution rule."""

    def test_resolves_a_mapped_identifier_to_its_username(self):
        """Return the provider's username for an identifier the map covers."""
        assert resolve_actor(CREATOR_ID, USERNAME_MAP) == "alice"

    def test_returns_none_for_a_missing_actor(self):
        """Keep ``None`` as ``None`` rather than coercing it to a blank string."""
        assert resolve_actor(None, USERNAME_MAP) is None

    def test_returns_the_identifier_when_the_map_does_not_cover_it(self):
        """Degrade to the stored identifier when the provider cannot resolve it."""
        assert resolve_actor(UNKNOWN_ID, USERNAME_MAP) == UNKNOWN_ID

    def test_returns_the_identifier_when_the_map_is_empty(self):
        """Degrade every actor when the provider lookup returned nothing."""
        assert resolve_actor(CREATOR_ID, {}) == CREATOR_ID

    def test_labels_the_system_sentinel(self):
        """Render the ``SYSTEM`` executor sentinel as its display label."""
        assert resolve_actor(SYSTEM_USER, {}) == "System"

    def test_labels_the_service_principal(self):
        """Render the service-principal identifier as its display label."""
        assert resolve_actor(str(SERVICE_PRINCIPAL_ID), {}) == "Service account"

    def test_system_label_wins_over_the_username_map(self):
        """Prefer the system label even if a provider improbably claims the id."""
        assert resolve_actor(SYSTEM_USER, {SYSTEM_USER: "someone"}) == "System"


def test_system_actor_labels_cover_every_system_executor_id():
    """Label exactly the identifiers the task-history SQL filter treats as system."""
    assert set(SYSTEM_ACTOR_LABELS) == SYSTEM_EXECUTOR_IDS


class TestResolveTaskActors:
    """Cover the typed task-definition resolver."""

    def test_resolves_both_actor_fields(self):
        """Rewrite the creator and last-updater to their display names."""
        task = SepTaskResponse.model_validate(_task_payload())

        resolved = resolve_task_actors(task, USERNAME_MAP)

        assert (resolved.created_by, resolved.last_updated_by) == ("alice", "bob")

    def test_returns_the_same_object(self):
        """Rewrite in place so a call site can use the return as an expression."""
        task = SepTaskResponse.model_validate(_task_payload())

        assert resolve_task_actors(task, USERNAME_MAP) is task

    def test_keeps_a_missing_actor_as_none(self):
        """Leave an unrecorded actor as ``None`` rather than a blank string."""
        task = SepTaskResponse.model_validate(_task_payload(created_by=None))

        resolved = resolve_task_actors(task, USERNAME_MAP)

        assert resolved.created_by is None


class TestResolveTaskHistoryActors:
    """Cover the typed page resolver across all three actor fields."""

    @staticmethod
    def _page(*rows: dict[str, Any]) -> PaginatedResponse[SepTaskHistoryResponse]:
        """Validate the supplied rows into a single paginated response."""
        return PaginatedResponse.from_pagination(
            [SepTaskHistoryResponse.model_validate(row) for row in rows],
            len(rows),
            Pagination(offset=0, limit=50),
        )

    def test_resolves_all_three_actor_fields(self):
        """Rewrite the row's executor and both actors on its nested task."""
        page = self._page(_history_payload())

        resolved = resolve_task_history_actors(page, USERNAME_MAP)

        row = resolved.items[0]
        assert row.executed_by == "carol"
        assert row.task.created_by == "alice"
        assert row.task.last_updated_by == "bob"

    def test_renders_a_system_executed_row(self):
        """Render a system-initiated row's executor as its display label."""
        page = self._page(_history_payload(executed_by=SYSTEM_USER))

        resolved = resolve_task_history_actors(page, USERNAME_MAP)

        assert resolved.items[0].executed_by == "System"

    def test_degrades_an_unresolvable_actor_to_its_identifier(self):
        """Leave an identifier the provider does not know unchanged."""
        page = self._page(_history_payload(executed_by=UNKNOWN_ID))

        resolved = resolve_task_history_actors(page, USERNAME_MAP)

        assert resolved.items[0].executed_by == UNKNOWN_ID

    def test_handles_an_empty_page(self):
        """Return an empty page untouched rather than iterating nothing badly."""
        page = self._page()

        assert resolve_task_history_actors(page, USERNAME_MAP).items == []

    def test_nested_task_is_the_sep_subclass(self):
        """Narrow the nested task to the SEP-owned type, not the shared one."""
        row = SepTaskHistoryResponse.model_validate(_history_payload())

        assert isinstance(row.task, SepTaskResponse)

    def test_subclass_keeps_every_key_the_upstream_row_carried(self):
        """Drop no declared upstream key when validating through the subclass."""
        payload = _history_payload()

        dumped = SepTaskHistoryResponse.model_validate(payload).model_dump(mode="json")

        assert set(payload)
        assert set(payload) <= set(dumped)


class TestResolveHistoryPayloadActors:
    """Cover the untyped passthrough resolver and its wrong-shape guards."""

    def test_resolves_all_three_fields_on_a_well_formed_page(self):
        """Rewrite the executor and both nested task actors on each row."""
        payload = {"items": [_history_payload()]}

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP)

        row = resolved["items"][0]
        assert row["executed_by"] == "carol"
        assert row["task"]["created_by"] == "alice"
        assert row["task"]["last_updated_by"] == "bob"

    def test_renders_a_system_executed_row(self):
        """Render a system-initiated row's executor as its display label."""
        payload = {"items": [_history_payload(executed_by=str(SERVICE_PRINCIPAL_ID))]}

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP)

        assert resolved["items"][0]["executed_by"] == "Service account"

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({}, id="items-missing"),
            pytest.param({"items": "nope"}, id="items-not-a-list"),
            pytest.param({"items": None}, id="items-none"),
        ],
    )
    def test_returns_a_page_without_usable_items_unchanged(
        self, payload: dict[str, Any]
    ):
        """Leave a page whose ``items`` is absent or not a list untouched."""
        assert resolve_history_payload_actors(dict(payload), USERNAME_MAP) == payload

    def test_skips_a_row_that_is_not_a_mapping(self):
        """Degrade one malformed row rather than failing the whole page."""
        payload = {"items": [None, _history_payload()]}

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP)

        assert resolved["items"][0] is None
        assert resolved["items"][1]["executed_by"] == "carol"

    def test_resolves_the_executor_when_the_nested_task_is_not_a_mapping(self):
        """Resolve the row's own executor even when its task is unusable."""
        payload = {"items": [_history_payload(task=None)]}

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP)

        assert resolved["items"][0]["executed_by"] == "carol"

    def test_does_not_add_an_absent_actor_key(self):
        """Leave a row that carries no ``executed_by`` key without one."""
        row = _history_payload()
        del row["executed_by"]

        resolved = resolve_history_payload_actors({"items": [row]}, USERNAME_MAP)

        assert "executed_by" not in resolved["items"][0]

    def test_preserves_keys_the_typed_model_does_not_declare(self):
        """Keep an unknown upstream key that validation would have dropped."""
        payload = {"items": [_history_payload(future_field="kept")]}

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP)

        assert resolved["items"][0]["future_field"] == "kept"

    def test_returns_the_same_mapping(self):
        """Rewrite in place so a call site can use the return as an expression."""
        payload = {"items": [_history_payload()]}

        assert resolve_history_payload_actors(payload, USERNAME_MAP) is payload
