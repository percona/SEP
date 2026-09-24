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

"""Cover the PMM Extensions owned task-history actor types and their resolvers."""

from typing import Any

import pytest

from app.api.deps import SERVICE_PRINCIPAL_ID
from app.core.pagination import PaginatedResponse, Pagination
from app.extensions.api.task_history_actors import (
    ExtensionsTaskHistoryResponse,
    ExtensionsTaskResponse,
    resolve_actor,
    resolve_history_payload_actors,
    resolve_task_actors,
    resolve_task_history_actors,
    SepHistoryPayload,
    SYSTEM_ACTOR_LABELS,
    TASK_ACTOR_FIELDS,
    task_actor_fields,
)
from app.tasks.crud import SYSTEM_EXECUTOR_IDS
from app.tasks.execution_request_secrets import ARGS_LEAF
from app.tasks.models import SYSTEM_USER, Task, TaskBackendEnum, TaskResponse
from tests.app.factories import MOCK_CREATOR_ID as CREATOR_ID
from tests.app.factories import MOCK_UPDATER_ID as UPDATER_ID
from tests.app.factories import TaskFactory

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


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(Task, id="Task"),
        pytest.param(TaskResponse, id="TaskResponse"),
        pytest.param(ExtensionsTaskResponse, id="ExtensionsTaskResponse"),
    ],
)
def test_actor_fields_are_declared_on_every_owning_task_model(
    model: type[Task | TaskResponse | ExtensionsTaskResponse],
):
    """Pin TASK_ACTOR_FIELDS to fields the owning task models actually declare.

    A rename on the owning model must fail here rather than leave the resolver
    and the framework conformance check keyed on stale field names.
    """
    assert TASK_ACTOR_FIELDS
    assert set(TASK_ACTOR_FIELDS) <= model.model_fields.keys()


class TestResolveTaskActors:
    """Cover the typed task-definition resolver."""

    def test_resolves_both_actor_fields(self):
        """Rewrite the creator and last-updater to their display names."""
        task = ExtensionsTaskResponse.model_validate(_task_payload())

        resolved = resolve_task_actors(task, USERNAME_MAP)

        assert (resolved.created_by, resolved.last_updated_by) == ("alice", "bob")

    def test_returns_the_same_object(self):
        """Rewrite in place so a call site can use the return as an expression."""
        task = ExtensionsTaskResponse.model_validate(_task_payload())

        assert resolve_task_actors(task, USERNAME_MAP) is task

    def test_keeps_a_missing_actor_as_none(self):
        """Leave an unrecorded actor as ``None`` rather than a blank string."""
        task = ExtensionsTaskResponse.model_validate(_task_payload(created_by=None))

        resolved = resolve_task_actors(task, USERNAME_MAP)

        assert resolved.created_by is None


class TestTaskActorFields:
    """Cover the actor-field extras a task response builder spreads."""

    def test_resolves_both_actor_fields(self):
        """Map the creator and last-updater to their provider usernames."""
        task = TaskFactory.build(created_by=CREATOR_ID, last_updated_by=UPDATER_ID)

        assert task_actor_fields(task, USERNAME_MAP) == {
            "created_by": "alice",
            "last_updated_by": "bob",
        }

    def test_system_label_wins_over_the_username_map(self):
        """Render a service-principal creator as its label, whatever the map says."""
        service_principal = str(SERVICE_PRINCIPAL_ID)
        task = TaskFactory.build(
            created_by=service_principal, last_updated_by=UPDATER_ID
        )

        fields = task_actor_fields(task, {service_principal: "someone"})

        assert fields["created_by"] == "Service account"

    def test_degrades_unknown_and_missing_actors(self):
        """Keep an unresolvable identifier and leave an unrecorded actor ``None``."""
        task = TaskFactory.build(created_by=UNKNOWN_ID, last_updated_by=None)

        assert task_actor_fields(task, {}) == {
            "created_by": UNKNOWN_ID,
            "last_updated_by": None,
        }


class TestResolveTaskHistoryActors:
    """Cover the typed page resolver across all three actor fields."""

    @staticmethod
    def _page(
        *rows: dict[str, Any],
    ) -> PaginatedResponse[ExtensionsTaskHistoryResponse]:
        """Validate the supplied rows into a single paginated response."""
        return PaginatedResponse.from_pagination(
            [ExtensionsTaskHistoryResponse.model_validate(row) for row in rows],
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

    def test_nested_task_is_the_extensions_subclass(self):
        """Narrow the nested task to the PMM Extensions owned type, not the shared one."""
        row = ExtensionsTaskHistoryResponse.model_validate(_history_payload())

        assert isinstance(row.task, ExtensionsTaskResponse)

    def test_subclass_keeps_every_key_the_upstream_row_carried(self):
        """Drop no declared upstream key when validating through the subclass."""
        payload = _history_payload()

        dumped = ExtensionsTaskHistoryResponse.model_validate(payload).model_dump(
            mode="json"
        )

        assert set(payload)
        assert set(payload) <= set(dumped)


class TestResolveHistoryPayloadActors:
    """Cover the typed passthrough resolver and its wrong-shape guards."""

    @staticmethod
    def _payload(raw: dict[str, Any]) -> SepHistoryPayload:
        """Validate a raw history page into the typed envelope under test."""
        return SepHistoryPayload.model_validate(raw)

    def test_resolves_all_three_fields_on_a_well_formed_page(self):
        """Rewrite the executor and both nested task actors on each row."""
        payload = self._payload({"items": [_history_payload()]})

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP).model_dump(
            exclude_unset=True
        )

        row = resolved["items"][0]
        assert row["executed_by"] == "carol"
        assert row["task"]["created_by"] == "alice"
        assert row["task"]["last_updated_by"] == "bob"

    def test_renders_a_system_executed_row(self):
        """Render a system-initiated row's executor as its display label."""
        payload = self._payload(
            {"items": [_history_payload(executed_by=str(SERVICE_PRINCIPAL_ID))]}
        )

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP).model_dump(
            exclude_unset=True
        )

        assert resolved["items"][0]["executed_by"] == "Service account"

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param({}, id="items-missing"),
            pytest.param({"items": "nope"}, id="items-not-a-list"),
            pytest.param({"items": None}, id="items-none"),
        ],
    )
    def test_returns_a_page_without_usable_items_unchanged(self, raw: dict[str, Any]):
        """Leave a page whose ``items`` is absent or not a list untouched."""
        payload = self._payload(raw)
        before = payload.model_dump(exclude_unset=True)

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP)

        assert resolved is payload
        assert resolved.model_dump(exclude_unset=True) == before

    def test_skips_a_row_that_is_not_a_mapping(self):
        """Degrade one malformed row rather than failing the whole page."""
        payload = self._payload({"items": [None, _history_payload()]})

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP).model_dump(
            exclude_unset=True
        )

        assert resolved["items"][0] is None
        assert resolved["items"][1]["executed_by"] == "carol"

    def test_resolves_the_executor_when_the_nested_task_is_not_a_mapping(self):
        """Resolve the row's own executor even when its task is unusable."""
        payload = self._payload({"items": [_history_payload(task=None)]})

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP).model_dump(
            exclude_unset=True
        )

        assert resolved["items"][0]["executed_by"] == "carol"

    def test_does_not_add_an_absent_actor_key(self):
        """Leave a row that carries no ``executed_by`` key without one."""
        row = _history_payload()
        del row["executed_by"]
        payload = self._payload({"items": [row]})

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP).model_dump(
            exclude_unset=True
        )

        assert "executed_by" not in resolved["items"][0]

    def test_preserves_keys_the_typed_model_does_not_declare(self):
        """Keep an unknown upstream key that a strict model would have dropped."""
        payload = self._payload({"items": [_history_payload(future_field="kept")]})

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP).model_dump(
            exclude_unset=True
        )

        assert resolved["items"][0]["future_field"] == "kept"

    @pytest.mark.parametrize(
        "actor",
        [
            pytest.param({"nested": "object"}, id="unhashable-mapping"),
            pytest.param(["a"], id="unhashable-list"),
            pytest.param(42, id="number"),
        ],
    )
    def test_leaves_a_non_string_actor_untouched(self, actor: Any):
        """Degrade an actor of an unexpected type rather than failing the page."""
        payload = self._payload({"items": [_history_payload(executed_by=actor)]})

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP).model_dump(
            exclude_unset=True
        )

        assert resolved["items"][0]["executed_by"] == actor

    def test_leaves_a_non_string_nested_actor_untouched(self):
        """Apply the same tolerance to the actors on a nested task."""
        row = _history_payload()
        row["task"]["created_by"] = {"nested": "object"}
        payload = self._payload({"items": [row]})

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP).model_dump(
            exclude_unset=True
        )

        assert resolved["items"][0]["task"]["created_by"] == {"nested": "object"}
        assert resolved["items"][0]["task"]["last_updated_by"] == "bob"

    def test_resolves_nested_actors_when_executed_by_has_an_unexpected_shape(self):
        """Keep a bad executor raw while still resolving both nested task actors."""
        payload = self._payload(
            {"items": [_history_payload(executed_by={"nested": "object"})]}
        )

        resolved = resolve_history_payload_actors(payload, USERNAME_MAP).model_dump(
            exclude_unset=True
        )

        row = resolved["items"][0]
        assert row["executed_by"] == {"nested": "object"}
        assert row["task"]["created_by"] == "alice"
        assert row["task"]["last_updated_by"] == "bob"

    def test_returns_the_same_payload(self):
        """Rewrite in place so a call site can use the return as an expression."""
        payload = self._payload({"items": [_history_payload()]})

        assert resolve_history_payload_actors(payload, USERNAME_MAP) is payload


class TestExtensionsTaskHistoryResponseUnreadableLeaves:
    """Cover the gateway's handling of an already-redacted upstream row."""

    def test_preserves_an_indicator_it_cannot_re_derive(self):
        """Keep the upstream indicator, which nothing downstream can reconstruct.

        The leaf is ``null`` by the time this model validates, so a computed
        field would report an empty list for a row the tasks service flagged.
        """
        row = _history_payload(
            execution_request={
                "task": "backup",
                "target": "host1",
                "meta": {"args": None},
            },
            unreadable_request_leaves=[ARGS_LEAF],
        )

        response = ExtensionsTaskHistoryResponse.model_validate(row)

        assert response.unreadable_request_leaves == [ARGS_LEAF]
        assert (response.execution_request.meta or {})["args"] is None

    def test_reports_no_leaves_for_a_clean_row(self):
        """Report an empty list for a row the tasks service read cleanly."""
        response = ExtensionsTaskHistoryResponse.model_validate(_history_payload())

        assert response.unreadable_request_leaves == []
