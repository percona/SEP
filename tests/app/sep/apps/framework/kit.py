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

"""Provide the framework test kit's boundary mocks and synthetic app definition.

The kit lets a plugin verify a ``TaskExecutionApp`` definition's derived HTTP
behavior by supplying only its definition. It pairs two stateful, byte-faithful
boundary mocks — :class:`MockTaskAPI` and :class:`MockInventoryAPI`, installed
through ``dependency_overrides`` for ``get_tasks_api`` / ``get_inventory_api`` —
with a canonical synthetic definition (:func:`synth_app`) the contract suite
runs green. The mocks mirror the real Tasks/Inventory boundary semantics
(``batch_get_latest_statuses`` chunking and degrade-to-``None``,
``get_created_entity`` resolution) so a migrated plugin's list/detail/create/
execute paths are tested against the same shapes production sees.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends
from pydantic import BaseModel, Field

from app.core.exceptions import HTTPConflictException, HTTPNotFoundException
from app.core.pagination import Pagination
from app.core.requests import as_json_object
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework import ConnectivityWarning
from app.sep.apps.framework.apps import (
    AppCapabilities,
    ListFilterConfig,
    TaskExecutionApp,
    Views,
)
from app.sep.apps.framework.deps import make_task_dep
from app.sep.apps.framework.form_dsl import (
    AppFormModel,
    FormLayout,
    HostRef,
    SectionLayout,
    ServiceRef,
    Ui,
)
from app.sep.apps.framework.responses import build_default_task_response
from app.sep.apps.framework.schema import AppSchema, Capabilities, Column, ListView
from app.sep.apps.framework.script_source import ScriptSource
from app.sep.apps.framework.spec import ResolvedEntities, RunCommandSpec
from app.sep.apps.framework.task_status import batch_get_latest_statuses
from app.sep.deps import TaskAPI
from app.tasks.models import Task, TaskHistoryStatusEnum
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    MOCK_CREATED_NODE_ID,
    MOCK_CREATED_SCHEMA_ID,
    MOCK_CREATED_SERVICE_ID,
    MOCK_CREATED_TABLE_ID,
    TaskFactory,
    TaskHistoryResponseFactory,
)

SYNTH_OWNER = "ARCHIVER"
SYNTH_PREFIX = "/synthetic-app"
SYNTH_SCRIPT_PREFIX = "/synthetic-script-app"
SYNTH_SERVICE_HOST = "db-host"
SYNTH_SERVICE_PORT = 3306
SYNTH_EXECUTOR_HOST = "exec-node"

SEEDED_TASK_NAME = "contract-seeded-task"
SYNTH_CREATED_BY = "synth-user-id"
SYNTH_CREATED_BY_NAME = "synth-username"

_SYNTH_LAYOUT = FormLayout(sections=(SectionLayout(key="main", title="Main"),))
_SYNTH_ONEOF_LAYOUT = FormLayout(
    sections=(
        SectionLayout(key="main", title="Main"),
        SectionLayout(key="Source", title="Source"),
        SectionLayout(key="Sink", title="Sink"),
    )
)
_SYNTH_LIST_VIEW = ListView(columns=[Column(key="name", label="Name")])


class MockTaskAPI:
    """Serve Tasks-API calls from an in-memory, owner-filtered task store.

    A stateful, ``RemoteAPI``-shaped boundary mock installed through
    ``dependency_overrides[get_tasks_api]``. Each task carries a newest-first
    history list. ``POST /history/latest`` serves the ``{status, finished_at}``
    projection consumed by
    :func:`~app.sep.apps.framework.task_status.batch_get_latest_statuses` — the
    latest non-``None`` status per requested name and ``None`` for unknown names.
    Unknown detail names raise :class:`HTTPNotFoundException`, so
    ``get_task_by_name``'s 404 path fires without dependency stubbing.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._ids = count(1)
        self.create_count = 0
        self.last_create_payload: dict[str, Any] = {}
        self.last_update_payload: dict[str, Any] | None = None

    def seed_task(
        self,
        name: str,
        *,
        owner: str,
        statuses: Sequence[TaskHistoryStatusEnum] = (),
        created_by: str = SYNTH_CREATED_BY,
        protected: bool = False,
        parent: str | None = None,
        data_extra: dict[str, Any] | None = None,
    ) -> None:
        """Store a task owned by ``owner`` with a newest-first ``statuses`` history.

        :param name: The task name to seed.
        :param owner: The task owner the list/detail routes filter by.
        :param statuses: Execution statuses, newest first, seeded as history rows.
        :param created_by: The user id stamped as the task creator, so the
            response builder's context-driven username remap is exercisable.
        :param protected: Whether to mark the task protected, so a plugin's
            protected-task update guard is exercisable.
        :param parent: The parent task name stamped on ``data["parent"]``, so a
            derived-child row is excluded by a ``roots_only`` list. Defaults to
            ``None`` (a root task).
        :param data_extra: Extra ``data`` fields merged in (for example
            ``{"backup_type": "pbm_config"}``), so a server-side ``extra_params``
            filter is exercisable. Defaults to ``None``.
        """
        data = {"task": "noop", "meta": {}}
        if parent is not None:
            data["parent"] = parent
        if data_extra:
            data |= data_extra
        task = TaskFactory.build(
            name=name,
            owner=owner,
            data=data,
            created_by=created_by,
            protected=protected,
        )
        self._tasks[name] = task.model_dump(mode="json")
        self._history[name] = [
            TaskHistoryResponseFactory.build(status=status).model_dump(mode="json")
            for status in statuses
        ]

    def seed_running(self, name: str, *, owner: str) -> None:
        """Store a task with a RUNNING history so the conflict guard fires.

        :param name: The task name to seed.
        :param owner: The task owner the list/detail routes filter by.
        """
        self.seed_task(name, owner=owner, statuses=(TaskHistoryStatusEnum.RUNNING,))

    async def get(
        self, path: str, params: dict[str, Any] | None = None, **_: Any
    ) -> dict[str, Any]:
        """Route a Tasks-API GET to the list, history, or detail handler."""
        params = params or {}
        if path == "/":
            return self._list(params)
        if path.endswith("/history/"):
            name = path[1:].removesuffix("/history/")
            return self._history_response(name, params.get("status"))
        name = path.lstrip("/")
        if name not in self._tasks:
            raise HTTPNotFoundException
        return self._tasks[name]

    async def post(
        self, path: str, json: dict[str, Any] | None = None, **_: Any
    ) -> dict[str, Any]:
        """Route a Tasks-API POST to batch-status, execute, or create."""
        json = json or {}
        if path == "/history/latest":
            return {
                name: self._latest_projection(name) for name in json.get("names", [])
            }
        if path == "/connectivity-check/":
            return {"success": True, "error": None}
        if path.startswith("/execute/"):
            return TaskHistoryResponseFactory.build(id=next(self._ids)).model_dump(
                mode="json"
            )
        return self._create(json)

    async def put(
        self, path: str, json: dict[str, Any] | None = None, **_: Any
    ) -> dict[str, Any]:
        """Update a stored task by name, returning the updated payload."""
        name = path.lstrip("/")
        if name not in self._tasks:
            raise HTTPNotFoundException
        self.last_update_payload = json
        self._tasks[name].update(json or {})
        return self._tasks[name]

    async def delete(self, path: str, **_: Any) -> None:
        """Delete a stored task by name."""
        name = path.lstrip("/")
        if name not in self._tasks:
            raise HTTPNotFoundException
        del self._tasks[name]

    def _list(self, params: dict[str, Any]) -> dict[str, Any]:
        tasks = [
            task
            for task in self._tasks.values()
            if self._matches_list_params(task, params)
        ]
        total = len(tasks)
        offset, limit = params.get("offset"), params.get("limit")
        if offset is not None and limit is not None:
            tasks = tasks[offset : offset + limit]
        return {
            "items": tasks,
            "total": total,
            "offset": offset or 0,
            "limit": limit if limit is not None else total,
        }

    @staticmethod
    def _matches_list_params(task: dict[str, Any], params: dict[str, Any]) -> bool:
        """Apply the server-side owner / ``parent_is_null`` / data-field filters.

        Mirrors the Tasks API's upstream list query so a ``roots_only`` or
        ``extra_params`` derived list is exercised end-to-end: ``owner`` matches
        the task owner, ``parent_is_null`` gates on ``data["parent"]``, and any
        remaining non-pagination key matches a ``data`` field by string value.
        """
        owner = params.get("owner")
        if owner is not None and task["owner"] != owner:
            return False
        data = task["data"]
        parent_is_null = params.get("parent_is_null")
        if parent_is_null is not None:
            want_root = parent_is_null in ("true", True)
            if want_root == bool(data.get("parent")):
                return False
        reserved = {"owner", "offset", "limit", "parent_is_null"}
        for key, value in params.items():
            if key in reserved:
                continue
            if str(data.get(key, "")) != str(value):
                return False
        return True

    def _history_response(
        self, name: str, status: TaskHistoryStatusEnum | str | None
    ) -> dict[str, Any]:
        items = self._history.get(name, [])
        if status is not None:
            items = [item for item in items if item.get("status") == status]
        return {"items": items}

    def _latest_projection(self, name: str) -> dict[str, Any] | None:
        """Mirror ``latest_status_by_task_names``: newest status + max finish.

        Returns ``None`` when no history row carries a non-null status (matching
        the real endpoint, which filters null-status rows), else the newest
        status paired with the ``max`` ``finished_at`` across the task's
        status-bearing rows.
        """
        items = self._history.get(name, [])
        status = next(
            (s for item in items if (s := item.get("status")) is not None), None
        )
        if status is None:
            return None
        finishes = [
            f
            for item in items
            if item.get("status") is not None
            and (f := item.get("finished_at")) is not None
        ]
        return {"status": status, "finished_at": max(finishes, default=None)}

    def _create(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.create_count += 1
        self.last_create_payload = payload
        created = TaskFactory.build(
            name=payload["name"],
            owner=payload["owner"],
            data=payload["data"],
            backend=payload.get("backend", TaskFactory.backend),
            alert_on_fail=payload.get("alert_on_fail", False),
            created_by=SYNTH_CREATED_BY,
        )
        stored = created.model_dump(mode="json")
        self._tasks[created.name] = stored
        self._history.setdefault(created.name, [])
        return stored


class MockInventoryAPI:
    """Resolve created inventory entities by id, ``get_created_entity``-compatible.

    A stateful, ``RemoteAPI``-shaped boundary mock installed through
    ``dependency_overrides[get_inventory_api]``. Serves
    ``GET /{services|schemas|tables|nodes}/{id}`` as raw dicts that
    ``model_validate`` into the matching ``Created*`` model, seeded by default at
    the ``MOCK_*_ID`` constants. The default service is MySQL-typed so a
    single-type ``ServiceRef(MYSQL)`` selector resolves through
    ``get_created_entity``'s equality filter. Unknown ids raise
    :class:`HTTPNotFoundException`.

    The default seeds materialise on first resolution rather than in
    ``__init__``, so a test that never resolves an entity pays nothing for them.
    An explicit ``seed_*`` call drops the matching default, so a test re-seeding
    an id — ``backup_pg``'s PostgreSQL-typed service, say — always wins over it.
    """

    def __init__(self) -> None:
        self._entities: dict[str, dict[int, dict[str, Any]]] = {
            "/services": {},
            "/schemas": {},
            "/tables": {},
            "/nodes": {},
        }
        self._pending: dict[tuple[str, int], Callable[[], None]] = {
            ("/nodes", MOCK_CREATED_NODE_ID): lambda: self.seed_node(
                MOCK_CREATED_NODE_ID
            ),
            ("/services", MOCK_CREATED_SERVICE_ID): lambda: self.seed_service(
                MOCK_CREATED_SERVICE_ID
            ),
            ("/schemas", MOCK_CREATED_SCHEMA_ID): lambda: self.seed_schema(
                MOCK_CREATED_SCHEMA_ID
            ),
            ("/tables", MOCK_CREATED_TABLE_ID): lambda: self.seed_table(
                MOCK_CREATED_TABLE_ID
            ),
        }

    def seed_node(self, node_id: int) -> None:
        """Seed a created node at ``node_id``."""
        self._pending.pop(("/nodes", node_id), None)
        self._entities["/nodes"][node_id] = CreatedNodeFactory.build(
            id=node_id, address=SYNTH_SERVICE_HOST
        ).model_dump(mode="json")

    def seed_service(
        self,
        service_id: int,
        *,
        service_type: ServiceTypeEnum = ServiceTypeEnum.MYSQL,
    ) -> None:
        """Seed a created service at ``service_id`` with ``service_type``."""
        self._pending.pop(("/services", service_id), None)
        self._entities["/services"][service_id] = CreatedServiceFactory.build(
            id=service_id,
            node=CreatedNodeFactory.build(address=SYNTH_SERVICE_HOST),
            type=service_type,
            name=f"svc-{service_id}",
            port=SYNTH_SERVICE_PORT,
        ).model_dump(mode="json")

    def seed_schema(self, schema_id: int) -> None:
        """Seed a created schema at ``schema_id``."""
        self._pending.pop(("/schemas", schema_id), None)
        self._entities["/schemas"][schema_id] = CreatedSchemaFactory.build(
            id=schema_id
        ).model_dump(mode="json")

    def seed_table(self, table_id: int) -> None:
        """Seed a created table at ``table_id`` with an id-derived name.

        The name is derived from ``table_id`` (not left to a random factory value) so
        distinct table ids never collide by name — some task plugins guard against
        operations where source and destination resolve to the same table name.
        """
        self._pending.pop(("/tables", table_id), None)
        self._entities["/tables"][table_id] = CreatedTableFactory.build(
            id=table_id, name=f"tbl-{table_id}"
        ).model_dump(mode="json")

    async def get(self, path: str, **_: Any) -> dict[str, Any]:
        """Resolve ``GET /{collection}/{id}`` against the seeded entity store.

        A miss falls back to the default seed pending for that id, so the
        ``MOCK_*_ID`` entities cost their factory build only in a test that
        actually resolves them.
        """
        collection, _, entity_id = path.rpartition("/")
        store = self._entities.get(collection)
        if store is None or not entity_id.isdigit():
            raise HTTPNotFoundException
        key = int(entity_id)
        entity = store.get(key)
        if entity is None:
            seed = self._pending.pop((collection, key), None)
            if seed is None:
                raise HTTPNotFoundException
            seed()
            entity = store[key]
        return entity


class SynthForm(AppFormModel):
    """Represent a realistic synthetic create form covering the framework seams.

    Mirrors the shape every audited real task plugin hits: an executor ``HostRef``
    distinct from the service ``ServiceRef``, a form-display default differing from
    the model default (``mode``), and the inherited ``alert_on_fail`` capability
    control excluded from the schema (rendered by ``Capabilities(alert_on_fail=True)``).
    """

    task_name: Annotated[str, Ui(label="Name", section="main")]
    service_id: Annotated[
        int,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,)),
        Ui(label="Service", section="main"),
    ]
    host: Annotated[str, HostRef(), Ui(label="Host", section="main")]
    mode: Annotated[
        str, Ui(label="Mode", section="main", default="display-default")
    ] = "body-default"


class SynthConnectivityForm(SynthForm):
    """A ``SynthForm`` whose service ``ServiceRef`` enables the connectivity probe.

    The probe (and the auto-derived ``connectivity_warning`` create-response field)
    is derived from a ``check_connectivity=True`` ``ServiceRef`` rather than an
    app-level flag, so the connectivity variant marks ``service_id``.
    """

    service_id: Annotated[
        int,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,), check_connectivity=True),
        Ui(label="Service", section="main"),
    ]


class SynthSourceAlpha(BaseModel):
    """Represent the ``alpha`` branch of the synthetic ``source`` one-of.

    :param mode: The one-of discriminator (``"alpha"``).
    :param alpha_value: The branch's scalar payload.
    """

    mode: Literal["alpha"] = "alpha"
    alpha_value: Annotated[str, Ui(label="Alpha Value", section="Source")]


class SynthSourceBeta(BaseModel):
    """Represent the ``beta`` branch of the synthetic ``source`` one-of.

    :param mode: The one-of discriminator (``"beta"``).
    :param beta_count: The branch's scalar payload.
    """

    mode: Literal["beta"] = "beta"
    beta_count: Annotated[int, Ui(label="Beta Count", section="Source")]


class SynthSinkFile(BaseModel):
    """Represent the ``file`` branch of the optional synthetic ``sink`` one-of.

    :param mode: The one-of discriminator (``"file"``).
    :param file_path: The branch's scalar payload.
    """

    mode: Literal["file"] = "file"
    file_path: Annotated[str, Ui(label="File Path", section="Sink")]


class SynthSinkTable(BaseModel):
    """Represent the ``table`` branch of the optional synthetic ``sink`` one-of.

    :param mode: The one-of discriminator (``"table"``).
    :param table_name: The branch's scalar payload.
    """

    mode: Literal["table"] = "table"
    table_name: Annotated[str, Ui(label="Table Name", section="Sink")]


class SynthOneOfForm(SynthForm):
    """Represent a synthetic create form carrying discriminated-union fields.

    Mirrors the archives create model's shape — a required ``source`` one-of plus
    an optional ``sink`` one-of defaulting to ``None`` — so the framework's derived
    create and update routes both build a Pydantic v2 discriminated-union
    request-body schema. The one-of branches carry only plain scalars (no nested
    references), so the inherited top-level ``ServiceRef`` / ``HostRef`` still
    drive resolution while the one-of body path is exercised.

    :param source: The required ``alpha`` / ``beta`` one-of source selection.
    :param sink: The optional ``file`` / ``table`` one-of sink selection; ``None``
        omits it, mirroring archives' optional destination/host one-ofs.
    """

    source: Annotated[
        SynthSourceAlpha | SynthSourceBeta,
        Field(discriminator="mode"),
        Ui(section="Source"),
    ]
    sink: Annotated[
        SynthSinkFile | SynthSinkTable | None,
        Field(discriminator="mode"),
        Ui(section="Sink"),
    ] = None


class SynthResponse(BaseModel):
    """Represent the list/detail response built from the task dump plus status.

    Mirrors the audited plugins' response shape: ``service_type`` is stamped by
    the builder for internal use but excluded from the serialized payload (same
    contract as :class:`~app.sep.apps.framework.responses.BaseTaskResponse`),
    and ``created_by`` is remapped from the bound context's username map.
    """

    name: str
    status: TaskHistoryStatusEnum | None = None
    service_type: ServiceTypeEnum | None = Field(default=None, exclude=True)
    created_by: str | None = None


class SynthDetailResponse(SynthResponse):
    """Represent a detail response richer than the list response.

    Carries a ``detail_only`` field absent from the list model, so a detail (and
    the create-renders-like-detail) route is distinguishable from the list route.
    """

    detail_only: bool = True


class SynthCreateResponse(SynthResponse):
    """Represent a stable create response carrying the connectivity warning.

    A hand-authored create model (not the framework's auto-derived
    ``<App>CreateResponse``): it carries the same ``created_by`` remap as the
    list/detail response *plus* a ``connectivity_warning``, while omitting
    internal ``service_type`` from the serialized payload.
    """

    connectivity_warning: ConnectivityWarning | None = None


class SynthExecuteWrite(BaseModel):
    """Represent the execute request body for the synthetic app."""

    note: str | None = None


class SynthExecuteResponse(BaseModel):
    """Represent the execute response carrying the dispatched task name and id."""

    task_name: str
    task_id: int


class SynthCapabilities(BaseModel):
    """Represent the runtime capability flags returned by ``GET /capabilities``."""

    manual_sync_enabled: bool = True


_synth_task_dep = Depends(make_task_dep(SYNTH_OWNER))


def synth_capabilities_provider() -> SynthCapabilities:
    """Return the synthetic runtime capability flags."""
    return SynthCapabilities()


def synth_spec_builder(
    form: AppFormModel, resolved: ResolvedEntities
) -> RunCommandSpec:
    """Build a synthetic run-command spec from the form and resolved service."""
    service = resolved.service
    return RunCommandSpec(
        command="synth-cmd",
        args=f"--task={form.task_name}",
        extra_meta={
            "_service_host": service.node.address,
            "_service_port": service.port,
        },
    )


def synth_response_builder(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
    last_executed_at: datetime | None = None,
    context: dict[str, str] | None = None,
) -> SynthResponse:
    """Build the synth response, injecting extras and remapping ``created_by``.

    Mirrors the audited plugins' builders: a fixed ``service_type`` extra plus a
    ``created_by`` resolved through the bound context's username map with the
    ``.get(id, id)`` raw-id fallback, so a missing map entry surfaces the raw id.

    :param task: The task to build a response for.
    :param status: The latest known execution status.
    :param last_executed_at: The task's most recent finish time, injected by the
        framework.
    :param context: The bound username map, or ``None`` when no provider is wired.
    :return: The synth response carrying the injected extras.
    """
    mapping = context or {}
    return build_default_task_response(
        SynthResponse,
        task,
        status,
        last_executed_at=last_executed_at,
        extras={
            "service_type": ServiceTypeEnum.MYSQL,
            "created_by": mapping.get(task.created_by, task.created_by),
        },
    )


def synth_detail_builder(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
    last_executed_at: datetime | None = None,
    context: dict[str, str] | None = None,
) -> SynthDetailResponse:
    """Build the richer synth detail response, injecting extras and the username.

    A sync builder receiving the framework-injected ``status`` — the shape a real
    plugin's detail builder takes once it stops re-fetching the status itself.

    :param task: The task to build a response for.
    :param status: The latest known execution status, injected by the framework.
    :param last_executed_at: The task's most recent finish time, injected by the
        framework.
    :param context: The bound username map, or ``None`` when no provider is wired.
    :return: The richer synth detail response.
    """
    mapping = context or {}
    return build_default_task_response(
        SynthDetailResponse,
        task,
        status,
        last_executed_at=last_executed_at,
        extras={
            "service_type": ServiceTypeEnum.MYSQL,
            "created_by": mapping.get(task.created_by, task.created_by),
        },
    )


def synth_create_response_builder(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
    last_executed_at: datetime | None = None,
    context: dict[str, str] | None = None,
) -> SynthCreateResponse:
    """Build the stable create response, injecting extras and the resolved name.

    Mirrors :func:`synth_response_builder` but returns the stable
    :class:`SynthCreateResponse` component, so an app can wire one
    ``create_response_builder`` that keeps a ``connectivity_warning`` on a
    hand-authored model rather than the framework's auto-derived one.

    :param task: The task to build a response for.
    :param status: The latest known execution status.
    :param last_executed_at: The task's most recent finish time, injected by the
        framework.
    :param context: The bound username map, or ``None`` when no provider is wired.
    :return: The stable create response carrying the injected extras.
    """
    mapping = context or {}
    return build_default_task_response(
        SynthCreateResponse,
        task,
        status,
        last_executed_at=last_executed_at,
        extras={
            "service_type": ServiceTypeEnum.MYSQL,
            "created_by": mapping.get(task.created_by, task.created_by),
        },
    )


async def synth_context_provider() -> dict[str, str]:
    """Return the synthetic username map resolved once per request."""
    return {SYNTH_CREATED_BY: SYNTH_CREATED_BY_NAME}


async def synth_reject_running_task(tasks_api: TaskAPI) -> None:
    """Reject create when the synth owner already has a RUNNING task.

    Mirrors backup_pg's ``HasNoConflictedRunningTasksOnCreate`` guard shape — a
    pre-create dependency that queries the Tasks API and raises a conflict — so
    ``create_extra_deps`` enforcement is exercised through the body graph.

    :param tasks_api: The Tasks API client used to look up the owner's tasks.
    :raises HTTPConflictException: When any owned task's latest status is RUNNING.
    """
    listing = as_json_object(await tasks_api.get("/", params={"owner": SYNTH_OWNER}))
    names = [item["name"] for item in listing["items"]]
    statuses = await batch_get_latest_statuses(tasks_api, names)
    if any(
        value is not None and value.status == TaskHistoryStatusEnum.RUNNING
        for value in statuses.values()
    ):
        raise HTTPConflictException("A synthetic task is already running.")


synth_create_guard = Depends(synth_reject_running_task)
synth_update_guard = Depends(synth_reject_running_task)


async def synth_delete_handler(
    task: Annotated[Task, _synth_task_dep], tasks_api: TaskAPI
) -> None:
    """Resolve the task (404 on unknown) and delete it upstream."""
    await tasks_api.delete(f"/{task.name}")


async def synth_update_handler(
    task: Annotated[Task, _synth_task_dep],
) -> SynthResponse:
    """Resolve the task and echo it, so an update-enabled synth app returns 200."""
    return SynthResponse(name=task.name)


def synth_app_kwargs() -> dict[str, Any]:
    """Return the canonical synthetic ``TaskExecutionApp`` constructor kwargs.

    :return: Fresh kwargs for the correct synthetic definition; callers merge
        overrides over these to derive read-only, paginated, or broken variants.
    """
    return {
        "name": "synthetic-app",
        "uri_path": SYNTH_PREFIX,
        "owner": SYNTH_OWNER,
        "create_model": SynthForm,
        "response_model": SynthResponse,
        "views": Views(
            layout=_SYNTH_LAYOUT,
            list_view=_SYNTH_LIST_VIEW,
            capabilities=Capabilities(alert_on_fail=True),
        ),
        "task_spec_builder": synth_spec_builder,
        "execute_write_model": SynthExecuteWrite,
        "execute_response_model": SynthExecuteResponse,
        "capabilities_provider": synth_capabilities_provider,
        "service_type": ServiceTypeEnum.MYSQL,
        "list_filter": ListFilterConfig(status=True, service_type=True),
        "response_builder": synth_response_builder,
        "response_context_provider": synth_context_provider,
        "create_extra_deps": (synth_create_guard,),
    }


def synth_app(**overrides: Any) -> TaskExecutionApp:
    """Build the canonical synthetic ``TaskExecutionApp`` with optional overrides.

    The connectivity probe is now derived from a ``check_connectivity=True``
    ``ServiceRef`` on the create model rather than an app-level flag, so a
    ``connectivity_check=True`` override is translated into the
    :class:`SynthConnectivityForm` create model (unless the caller pins its own
    ``create_model``).

    :param overrides: Fields merged over the canonical kwargs to derive variants.
    :return: A validated synthetic app definition the contract suite runs green.
    """
    if overrides.pop("connectivity_check", False):
        overrides.setdefault("create_model", SynthConnectivityForm)
    return TaskExecutionApp(**{**synth_app_kwargs(), **overrides})


def synth_oneof_app(**overrides: Any) -> TaskExecutionApp:
    """Build a synthetic ``TaskExecutionApp`` whose create model uses one-of bodies.

    Reuses the canonical synthetic kwargs but swaps in :class:`SynthOneOfForm`
    (discriminated-union ``source`` / ``sink`` fields), a layout covering their
    sections, and the update/delete capabilities — so the derived create *and*
    update routes both build a one-of request-body schema. This is the reusable
    fixture for the framework's one-of derived-router coverage.

    :param overrides: Fields merged over the one-of app kwargs to derive variants.
    :return: A validated synthetic one-of app definition.
    """
    kwargs = synth_app_kwargs()
    kwargs["create_model"] = SynthOneOfForm
    kwargs["views"] = Views(
        layout=_SYNTH_ONEOF_LAYOUT,
        list_view=_SYNTH_LIST_VIEW,
        capabilities=Capabilities(alert_on_fail=True),
    )
    kwargs["capabilities"] = AppCapabilities(update=True, delete=True)
    return TaskExecutionApp(**{**kwargs, **overrides})


class _SynthScript:
    """Represent a minimal script backing the synthetic script-flavored app."""

    def __init__(self, filename: str = "synth.sh") -> None:
        self.filename = filename

    @property
    def execution_task_name(self) -> str:
        """Return the fixed Tasks-API task name the synthetic script runs under."""
        return "synth-script-task"

    def get_execution_model(self) -> type[BaseModel]:
        """Return an empty execution-arguments model."""
        return BaseModel


class SynthScriptListRow(BaseModel):
    """Represent the list-row projection for the synthetic script app."""

    filename: str


_SYNTH_SCRIPT_SCHEMA = AppSchema(
    name="synthetic-script-app",
    display_name="Synthetic Script App",
    forms=[],
    list_view=ListView(columns=[Column(key="filename", label="Filename")]),
)


def _synth_script_source(scripts: Sequence[_SynthScript]) -> ScriptSource[_SynthScript]:
    """Build a minimal in-memory ``ScriptSource`` listing ``scripts``.

    :param scripts: The scripts the source's ``list_scripts`` hook returns.
    :return: A ``ScriptSource`` whose list route projects each script to a
        :class:`SynthScriptListRow`.
    """

    # Deliberately ignores ``list_query``: the synthetic app declares no
    # ``list_query_spec``, so the derived route never resolves one. Routing this through
    # the framework's applier would mean inventing a spec no assertion covers.
    async def _list_scripts(
        _list_query: Any, pagination: Pagination | None
    ) -> tuple[list[_SynthScript], int]:
        items = list(scripts)
        if pagination is None:
            return items, len(items)
        return pagination.slice(items), len(items)

    async def _load_script(filename: str) -> _SynthScript:
        return _SynthScript(filename)

    return ScriptSource(
        script_dir=Path("/synthetic-scripts"),
        load_script=_load_script,
        list_scripts=_list_scripts,
        build_form_schema=lambda _script: _SYNTH_SCRIPT_SCHEMA,
        build_execution_meta=lambda _script, _body: BaseModel(),
        list_response=lambda script: SynthScriptListRow(filename=script.filename),
        list_response_model=SynthScriptListRow,
    )


def synth_script_app(**overrides: Any) -> TaskExecutionApp:
    """Build a minimal script-flavored ``TaskExecutionApp`` with optional overrides.

    Mirror :func:`synth_app` for the ``script_source`` branch so the pagination
    default and the ``NO_PAGINATION`` opt-out can be exercised end-to-end against a
    script app, not only the CRUD flavor.

    :param overrides: Fields merged over the canonical script-app kwargs; the
        ``scripts`` key is popped to seed the source's listing.
    :return: A validated script-flavored synthetic app definition.
    """
    scripts = overrides.pop("scripts", (_SynthScript(),))
    kwargs = {
        "name": "synthetic-script-app",
        "uri_path": SYNTH_SCRIPT_PREFIX,
        "owner": SYNTH_OWNER,
        "script_source": _synth_script_source(scripts),
    }
    return TaskExecutionApp(**{**kwargs, **overrides})
