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

"""Tests for the shared JSON-API list-pipeline framework helpers."""

from collections import defaultdict
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.core.pagination import PaginatedResponse, Pagination
from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework import (
    BaseTaskResponse,
    build_default_task_response,
    build_task_list_responses,
    ConnectivityWarning,
    derive_create_response_model,
)
from app.sep.apps.framework.responses import dump_with_excluded_fields
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.models import Task, TaskHistoryStatusEnum
from tests.app.factories import TaskFactory


class _TaskResponse(BaseModel):
    """Minimal response model exercising the helper and the default builder."""

    model_config = ConfigDict(extra="allow")

    name: str
    status: TaskHistoryStatusEnum | None = None
    last_executed_at: datetime | None = None


def _build_response(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
    last_executed_at: datetime | None = None,
) -> _TaskResponse:
    """Build a minimal response carrying name, resolved status and last run."""
    return _TaskResponse(
        name=task.name, status=status, last_executed_at=last_executed_at
    )


def _task(name: str) -> Task:
    """Build a validatable archive task with the given name."""
    return TaskFactory.build(name=name, owner="ARCHIVER")


def _items(*names: str) -> list[dict]:
    """Return upstream ``items`` dicts that round-trip through ``Task``."""
    return [_task(name).model_dump() for name in names]


def _mock_tasks_api(
    *,
    items: list[dict],
    statuses: dict[str, str | None],
    finishes: dict[str, str | None] | None = None,
    total: int | None = None,
) -> AsyncMock:
    """Build a ``RemoteAPI`` mock returning ``items`` and batch projections.

    ``statuses`` maps name -> status string (or ``None`` for a name with no
    history, yielding a ``None`` wire value). ``finishes`` optionally maps
    name -> ISO ``finished_at`` string carried alongside the status.
    """
    finishes = finishes or {}
    payload = {"items": items}
    if total is not None:
        payload["total"] = total

    def _projection(name: str) -> dict | None:
        status = statuses.get(name)
        if status is None:
            return None
        return {"status": status, "finished_at": finishes.get(name)}

    tasks_api = AsyncMock(spec=RemoteAPI)
    tasks_api.get = AsyncMock(return_value=payload)
    tasks_api.post = AsyncMock(
        side_effect=lambda _path, json: {
            name: _projection(name) for name in json["names"]
        }
    )
    return tasks_api


class TestBuildTaskListResponses:
    """Test suite for ``build_task_list_responses``."""

    @pytest.mark.asyncio
    async def test_unpaginated_no_filter_builds_one_response_per_task(self) -> None:
        """Return a ``list`` with the builder called per task with its status."""
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "failed"},
        )

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
        )

        assert [(r.name, r.status) for r in result] == [
            ("task-a", TaskHistoryStatusEnum.SUCCESS),
            ("task-b", TaskHistoryStatusEnum.FAILED),
        ]

    @pytest.mark.asyncio
    async def test_status_filter_keeps_only_matching_status(self) -> None:
        """Return only items whose resolved status matches ``status_filter``."""
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "failed"},
        )

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
            status_filter=TaskHistoryStatusEnum.SUCCESS,
        )

        assert [r.name for r in result] == ["task-a"]

    @pytest.mark.asyncio
    async def test_last_executed_at_threaded_to_items(self) -> None:
        """Thread each task's ``finished_at`` onto the built response.

        Covers the in-progress-rerun case: ``task-b`` is RUNNING (so it does not
        match a SUCCESS filter) yet still carries its prior finish time, and a
        never-run ``task-c`` renders empty.
        """
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b", "task-c"),
            statuses={"task-a": "success", "task-b": "running", "task-c": None},
            finishes={
                "task-a": "2026-07-07T09:00:00",
                "task-b": "2026-07-06T12:00:00",
            },
        )

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
        )

        by_name = {r.name: r for r in result}
        assert by_name["task-a"].last_executed_at == datetime.fromisoformat(
            "2026-07-07T09:00:00"
        )
        assert by_name["task-b"].status == TaskHistoryStatusEnum.RUNNING
        assert by_name["task-b"].last_executed_at == datetime.fromisoformat(
            "2026-07-06T12:00:00"
        )
        assert by_name["task-c"].status is None
        assert by_name["task-c"].last_executed_at is None

    @pytest.mark.asyncio
    async def test_paginated_no_filter_uses_upstream_total(self) -> None:
        """Return a ``PaginatedResponse`` whose total echoes the upstream total."""
        upstream_total = 5
        pagination = Pagination(offset=0, limit=10)
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "failed"},
            total=upstream_total,
        )

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
            pagination=pagination,
        )

        assert isinstance(result, PaginatedResponse)
        assert result.total == upstream_total
        assert (result.offset, result.limit) == (pagination.offset, pagination.limit)
        assert [r.name for r in result.items] == ["task-a", "task-b"]

    @pytest.mark.asyncio
    async def test_paginated_status_filter_total_is_current_page_count(self) -> None:
        """Set total to the filtered current-page count when a filter is active."""
        pagination = Pagination(offset=0, limit=10)
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "failed"},
            total=5,
        )

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
            pagination=pagination,
            status_filter=TaskHistoryStatusEnum.SUCCESS,
        )

        assert result.total == 1
        assert [r.name for r in result.items] == ["task-a"]

    @pytest.mark.asyncio
    async def test_task_filter_excludes_from_batch_and_result(self) -> None:
        """Drop ``task_filter`` rejects before the batch-status call and result."""
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "success"},
        )

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
            task_filter=lambda task: task.name != "task-b",
        )

        assert [r.name for r in result] == ["task-a"]
        tasks_api.post.assert_awaited_once_with(
            "/history/latest", json={"names": ["task-a"]}
        )

    @pytest.mark.asyncio
    async def test_paginated_task_filter_total_is_current_page_count(self) -> None:
        """Set total to the filtered current-page count when task_filter drops rows."""
        pagination = Pagination(offset=0, limit=10)
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "success"},
            total=5,
        )

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
            pagination=pagination,
            task_filter=lambda task: task.name != "task-b",
        )

        assert result.total == 1
        assert [r.name for r in result.items] == ["task-a"]

    @pytest.mark.asyncio
    async def test_empty_items_returns_empty_list_without_post(self) -> None:
        """Return ``[]`` and issue no batch-status POST when there are no items."""
        tasks_api = _mock_tasks_api(items=[], statuses={})

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
        )

        assert result == []
        tasks_api.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_paginated_missing_total_falls_back_to_len(self) -> None:
        """Fall back to the item count when the paginated response omits total."""
        names = ["task-a", "task-b"]
        pagination = Pagination(offset=0, limit=10)
        tasks_api = _mock_tasks_api(
            items=_items(*names),
            statuses={"task-a": "success", "task-b": "failed"},
        )

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
            pagination=pagination,
        )

        assert result.total == len(names)

    @pytest.mark.asyncio
    async def test_owner_and_pagination_forwarded_in_get_params(self) -> None:
        """Forward owner and the pagination window in the upstream GET params."""
        pagination = Pagination(offset=20, limit=5)
        tasks_api = _mock_tasks_api(
            items=_items("task-a"),
            statuses={"task-a": "success"},
            total=1,
        )

        await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
            pagination=pagination,
        )

        tasks_api.get.assert_awaited_once_with(
            "/", params={"owner": "ARCHIVER", "offset": 20, "limit": 5}
        )

    @pytest.mark.asyncio
    async def test_context_provider_awaited_once_and_bound_into_every_builder_call(
        self,
    ) -> None:
        """Await the context provider once per page and bind it into each row build."""
        tasks_api = _mock_tasks_api(
            items=_items("task-a", "task-b"),
            statuses={"task-a": "success", "task-b": "failed"},
        )
        provider = AsyncMock(return_value={"u1": "Alice"})
        seen_contexts = []

        def _spy_builder(
            task: Task,
            *,
            status: TaskHistoryStatusEnum | None = None,
            last_executed_at: datetime | None = None,
            context: dict | None = None,
        ) -> _TaskResponse:
            seen_contexts.append(context)
            return _TaskResponse(
                name=task.name, status=status, last_executed_at=last_executed_at
            )

        await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_spy_builder,
            context_provider=provider,
        )

        provider.assert_awaited_once()
        assert seen_contexts == [{"u1": "Alice"}, {"u1": "Alice"}]

    @pytest.mark.asyncio
    async def test_context_provider_awaited_once_even_when_page_empty(self) -> None:
        """Await the provider exactly once even when the page yields no rows."""
        tasks_api = _mock_tasks_api(items=[], statuses={})
        provider = AsyncMock(return_value={})

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
            context_provider=provider,
        )

        assert result == []
        provider.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_context_provider_builds_without_context_kwarg(self) -> None:
        """Build through a context-free builder unchanged when no provider is given."""
        tasks_api = _mock_tasks_api(
            items=_items("task-a"),
            statuses={"task-a": "success"},
        )

        result = await build_task_list_responses(
            tasks_api,
            owner="ARCHIVER",
            response_builder=_build_response,
            context_provider=None,
        )

        assert [(r.name, r.status) for r in result] == [
            ("task-a", TaskHistoryStatusEnum.SUCCESS)
        ]


class TestBuildDefaultTaskResponse:
    """Test suite for ``build_default_task_response``."""

    def test_additive_extras_are_spread_onto_the_response(self) -> None:
        """Add extras as new fields on top of the dumped task payload."""
        task = _task("task-a")

        result = build_default_task_response(
            _TaskResponse,
            task,
            TaskHistoryStatusEnum.SUCCESS,
            extras={"hostname": "host-1"},
        )

        assert result.status == TaskHistoryStatusEnum.SUCCESS
        assert result.hostname == "host-1"

    def test_override_extras_win_over_dumped_value(self) -> None:
        """Let an extra override a field already present in the task dump."""
        task = _task("task-a")
        task.created_by = "user-id-1"

        result = build_default_task_response(
            _TaskResponse,
            task,
            extras={"created_by": "Alice"},
        )

        assert result.created_by == "Alice"

    def test_status_defaults_to_none_when_omitted(self) -> None:
        """Default the status to ``None`` when no status is supplied."""
        task = _task("task-a")

        result = build_default_task_response(_TaskResponse, task)

        assert result.status is None

    def test_injects_last_executed_at(self) -> None:
        """Inject the supplied ``last_executed_at`` onto the built response."""
        task = _task("task-a")
        finished = datetime.fromisoformat("2026-07-07T09:00:00")

        result = build_default_task_response(
            _TaskResponse,
            task,
            TaskHistoryStatusEnum.SUCCESS,
            last_executed_at=finished,
        )

        assert result.last_executed_at == finished

    def test_last_executed_at_defaults_to_none_when_omitted(self) -> None:
        """Default ``last_executed_at`` to ``None`` when not supplied."""
        task = _task("task-a")

        result = build_default_task_response(_TaskResponse, task)

        assert result.last_executed_at is None


class _CreateBase(BaseModel):
    """Represent a minimal base model for the create-response factory tests."""

    name: str
    backend: str


class TestDeriveCreateResponseModel:
    """Test suite for ``derive_create_response_model``."""

    def test_adds_connectivity_warning_and_preserves_base_fields(self) -> None:
        """Derive a model carrying every base field plus ``connectivity_warning``."""
        derived = derive_create_response_model(_CreateBase, name="ThingCreateResponse")

        assert set(_CreateBase.model_fields) <= set(derived.model_fields)
        assert "connectivity_warning" in derived.model_fields

    def test_connectivity_warning_is_optional_warning_defaulting_none(self) -> None:
        """Type the added field ``ConnectivityWarning | None`` defaulting to ``None``."""
        derived = derive_create_response_model(_CreateBase, name="ThingCreateResponse")
        field = derived.model_fields["connectivity_warning"]

        assert field.annotation == (ConnectivityWarning | None)
        assert field.default is None
        assert field.is_required() is False

    def test_name_fixes_class_name_and_schema_title(self) -> None:
        """Set ``model.__name__`` and the JSON-schema ``title`` from ``name``."""
        derived = derive_create_response_model(_CreateBase, name="ThingCreateResponse")

        assert derived.__name__ == "ThingCreateResponse"
        assert derived.model_json_schema()["title"] == "ThingCreateResponse"

    def test_doc_sets_docstring_and_schema_description(self) -> None:
        """Set the model docstring and schema ``description`` from ``doc``."""
        derived = derive_create_response_model(
            _CreateBase, name="ThingCreateResponse", doc="A derived create response."
        )

        assert derived.__doc__ == "A derived create response."
        assert (
            derived.model_json_schema()["description"] == "A derived create response."
        )

    def test_doc_none_yields_no_schema_description(self) -> None:
        """Omit the schema ``description`` when no ``doc`` is supplied."""
        derived = derive_create_response_model(_CreateBase, name="ThingCreateResponse")

        assert "description" not in derived.model_json_schema()

    def test_extra_fields_added_alongside_connectivity_warning(self) -> None:
        """Add cascade ``extra_fields`` beside the default ``connectivity_warning``."""
        derived = derive_create_response_model(
            _CreateBase,
            name="ThingCreateResponse",
            extra_fields={"pre_checks_auto_fire_warning": (str | None, None)},
        )

        assert "pre_checks_auto_fire_warning" in derived.model_fields
        assert "connectivity_warning" in derived.model_fields

    def test_extra_fields_cannot_clobber_connectivity_warning(self) -> None:
        """Keep the canonical ``connectivity_warning`` even when ``extra_fields`` collides."""
        derived = derive_create_response_model(
            _CreateBase,
            name="ThingCreateResponse",
            extra_fields={"connectivity_warning": (str, ...)},
        )
        field = derived.model_fields["connectivity_warning"]

        assert field.annotation == (ConnectivityWarning | None)
        assert field.is_required() is False


class TestBaseTaskResponse:
    """Test suite for the shared ``BaseTaskResponse`` model."""

    BASE_FIELDS: dict = {
        "name": "test-task",
        "owner": "CHECKSUMS",
        "backend": "nomad",
        "data": {},
        "protected": False,
        "alert_on_fail": False,
    }

    def test_explicit_mask_returns_sorted_entity_names(self) -> None:
        """Decode an explicit ``anonymize_mask`` to a sorted list of entity names."""
        mask = int(PIIEntity.IP_ADDRESS | PIIEntity.PERSON)

        response = BaseTaskResponse.model_validate(
            {**self.BASE_FIELDS, "anonymize_mask": mask}
        )

        assert response.anonymized_entities == ["IP_ADDRESS", "PERSON"]

    def test_zero_mask_returns_empty_list(self) -> None:
        """Decode ``anonymize_mask=0`` to an empty list (no entities set)."""
        response = BaseTaskResponse.model_validate(
            {**self.BASE_FIELDS, "anonymize_mask": 0}
        )

        assert response.anonymized_entities == []

    def test_none_mask_falls_back_to_owner_defaults(self) -> None:
        """Fall back to ``DEFAULT_ENTITIES[owner]`` when ``anonymize_mask`` is ``None``."""
        default_entities = {PIIEntity.EMAIL_ADDRESS}
        mock_defaults = defaultdict(lambda: default_entities)
        fields = {**self.BASE_FIELDS, "anonymize_mask": None}

        with patch(
            "app.sep.apps.framework.responses.anonymizer_settings"
        ) as mock_settings:
            mock_settings.DEFAULT_ENTITIES = mock_defaults
            response = BaseTaskResponse.model_validate(fields)
            result = response.anonymized_entities

        assert result == ["EMAIL_ADDRESS"]

    def test_serialized_payload_omits_owner_and_service_type(self) -> None:
        """Drop ``owner`` and ``service_type`` from the serialized detail/list payload."""
        response = BaseTaskResponse.model_validate(
            {**self.BASE_FIELDS, "service_type": ServiceTypeEnum.MYSQL.value}
        )

        dumped = response.model_dump(mode="json")

        assert response.owner == "CHECKSUMS"
        assert response.service_type is not None
        assert "owner" not in dumped
        assert "service_type" not in dumped

    def test_model_dump_with_excluded_fields_restores_excluded_fields(self) -> None:
        """Include ``owner`` and ``service_type`` in rebuild dumps used by detail builders."""
        response = BaseTaskResponse.model_validate(
            {**self.BASE_FIELDS, "service_type": ServiceTypeEnum.MYSQL.value}
        )

        dumped = response.model_dump_with_excluded_fields()

        assert dumped["owner"] == "CHECKSUMS"
        assert dumped["service_type"] == ServiceTypeEnum.MYSQL
        assert "anonymized_entities" not in dumped
        assert BaseTaskResponse.model_validate(dumped).owner == "CHECKSUMS"

    def test_dump_with_excluded_fields_honours_explicit_exclude(self) -> None:
        """Let an explicit ``exclude`` entry win over excluded-field reinjection."""
        response = BaseTaskResponse.model_validate(self.BASE_FIELDS)

        dumped = response.model_dump_with_excluded_fields(exclude={"owner"})

        assert "owner" not in dumped
        assert "service_type" in dumped

    def test_dump_with_excluded_fields_restores_exclude_true_fields_on_any_model(
        self,
    ) -> None:
        """Restore every ``Field(exclude=True)`` attribute for non-BaseTaskResponse models."""

        class _ExcludedResponse(BaseModel):
            name: str
            service_type: ServiceTypeEnum | None = Field(default=None, exclude=True)

        response = _ExcludedResponse(name="task-a", service_type=ServiceTypeEnum.MYSQL)

        dumped = dump_with_excluded_fields(response)

        assert dumped["name"] == "task-a"
        assert dumped["service_type"] == ServiceTypeEnum.MYSQL
        assert "service_type" not in response.model_dump()

    def test_anonymized_entities_still_resolves_when_owner_excluded(self) -> None:
        """Keep ``owner`` available to ``anonymized_entities`` despite serialization exclude."""
        default_entities = {PIIEntity.EMAIL_ADDRESS}
        mock_defaults = defaultdict(lambda: default_entities)
        fields = {**self.BASE_FIELDS, "anonymize_mask": None}

        with patch(
            "app.sep.apps.framework.responses.anonymizer_settings"
        ) as mock_settings:
            mock_settings.DEFAULT_ENTITIES = mock_defaults
            response = BaseTaskResponse.model_validate(fields)
            dumped = response.model_dump(mode="json")

        assert "owner" not in dumped
        assert dumped["anonymized_entities"] == ["EMAIL_ADDRESS"]

    def test_round_trips_task_dump_with_connectivity_warning_default_none(self) -> None:
        """Build from a task dump, defaulting ``connectivity_warning`` to ``None``."""
        task = TaskFactory.build(name="task-a", owner="CHECKSUMS")

        result = build_default_task_response(
            BaseTaskResponse, task, TaskHistoryStatusEnum.SUCCESS
        )

        assert result.name == "task-a"
        assert result.status == TaskHistoryStatusEnum.SUCCESS
        assert result.connectivity_warning is None
