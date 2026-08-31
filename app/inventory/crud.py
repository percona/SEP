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

"""Define database operations for the Inventory API."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any, ClassVar, TYPE_CHECKING

from sqlalchemy import literal, Update, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import ColumnElement, ColumnExpressionArgument
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import ListQuerySpec
from app.core.db.crud import BaseSQLModelChildManager, BaseSQLModelManager, W
from app.core.exceptions import HTTPConflictException
from app.core.utils.date_time import utc_now
from app.inventory.constants import ACTIVE_RETIREMENT_KEY, RetirableEntityName
from app.inventory.models import (
    HostSystemObservation,
    Node,
    RetirableSQLModel,
    Schema,
    Service,
    ServiceSystemObservation,
    Table,
)

if TYPE_CHECKING:
    from sqlmodel.sql.expression import SelectOfScalar


def _retire(
    model: type[RetirableSQLModel],
    *whereclause: ColumnExpressionArgument[bool],
    retired_at: datetime,
) -> Update:
    """Build the UPDATE retiring every active row matching the clauses.

    :param model: The table to retire rows in.
    :param whereclause: Clauses narrowing the rows to retire.
    :param retired_at: The timestamp to stamp on each retired row.
    :return: The UPDATE statement.
    """
    return (
        update(model)
        .where(col(model.retired_at).is_(None), *whereclause)
        .values(retired_at=retired_at, retirement_key=col(model.id))
    )


def _revive(
    model: type[RetirableSQLModel], *whereclause: ColumnExpressionArgument[bool]
) -> Update:
    """Build the UPDATE clearing retirement on every retired row matching the clauses.

    :param model: The table to revive rows in.
    :param whereclause: Clauses narrowing the rows to revive.
    :return: The UPDATE statement.
    """
    return (
        update(model)
        .where(col(model.retired_at).is_not(None), *whereclause)
        .values(retired_at=None, retirement_key=ACTIVE_RETIREMENT_KEY)
    )


def _retained(
    model: type[RetirableSQLModel],
    retired_before: datetime,
    keep_ids: Collection[int],
) -> ColumnElement[bool]:
    """Build the predicate matching rows collection must leave in place.

    A row is retained when it is still active, when its tombstone has not aged
    past the cutoff, or when the caller declared something still resolves it.

    :param model: The table to build the predicate against.
    :param retired_before: The cutoff a tombstone must predate to be collectible.
    :param keep_ids: The ids the caller declared still referenced.
    :return: The predicate matching this table's retained rows.
    """
    clauses = [
        col(model.retired_at).is_(None),
        col(model.retired_at) >= retired_before,
    ]
    if keep_ids:
        clauses.append(col(model.id).in_(keep_ids))
    return or_(*clauses)


def _retained_descendant_exists(
    subtree: Sequence[tuple[type[RetirableSQLModel], str]],
    parent_id: ColumnElement,
    retired_before: datetime,
    keep_by_model: Mapping[type[RetirableSQLModel], Collection[int]],
) -> ColumnElement[bool] | None:
    """Build the predicate matching an ancestor some descendant still pins.

    The subtree is a linear descent, so each level correlates on its own parent
    and nests the level below it. Expressing the descent in SQL rather than
    materializing the retained ids keeps the scan independent of how large the
    active inventory is.

    :param subtree: The descendant models, nearest first, each paired with the
        foreign key naming its own parent.
    :param parent_id: The primary-key column the nearest descendant correlates on.
    :param retired_before: The cutoff a tombstone must predate to be collectible.
    :param keep_by_model: The ids the caller declared still referenced, per table.
    :return: The predicate, or None when the subtree is empty.
    """
    if not subtree:
        return None
    (model, foreign_key), rest = subtree[0], subtree[1:]
    retained = [_retained(model, retired_before, keep_by_model.get(model, ()))]
    deeper = _retained_descendant_exists(
        rest, col(model.id), retired_before, keep_by_model
    )
    if deeper is not None:
        retained.append(deeper)
    return (
        select(literal(1))
        .where(col(getattr(model, foreign_key)) == parent_id, or_(*retained))
        .exists()
    )


class RetirableManagerMixin(BaseSQLModelManager):
    """Confine an entity's reads to the tombstone policy.

    ``_filter_query`` is the single funnel every read reaches, so overriding it
    covers ``list``, ``first``, ``get``, ``get_or_404``, ``list_query_paginated``,
    ``count`` and ``exists`` at once. It also reaches the bulk DML helpers, so
    ``update_where`` and ``delete_where`` can never touch a tombstone through the
    default managers — a collection job will have to go through the retired-
    inclusive siblings or it will silently match nothing. The opt-out rides
    ``cls`` rather than a call argument because ``BaseManager._select`` splits a
    paginated ``select_related`` read into a page query and a hydration query and
    forwards neither ``equal_filters`` nor the original clauses to the second one:
    an opt-out passed per call would be dropped there and the injection would fire
    on the hydration query alone, returning a short page whose ``total`` does not
    match it.

    :cvar include_retired: Whether reads through this manager see tombstones.
    :cvar retirement_subtree: The descendant models retirement cascades into,
        nearest first, each paired with the foreign key naming its own parent.
    """

    include_retired: ClassVar[bool] = False
    retirement_subtree: ClassVar[tuple[tuple[type[RetirableSQLModel], str], ...]] = ()

    @classmethod
    def _filter_query(
        cls,
        query: W,
        *whereclause: ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        query_options: Sequence = (),
        **equal_filters: Any,
    ) -> W:
        if not cls.include_retired:
            whereclause = (*whereclause, col(cls.Model.retired_at).is_(None))
            select_related = cls._scope_eager_loads(select_related)
        return super()._filter_query(
            query,
            *whereclause,
            select_related=select_related,
            query_options=query_options,
            **equal_filters,
        )

    @classmethod
    def _scope_eager_loads(cls, select_related: Sequence) -> Sequence:
        """Restrict eagerly-loaded retirable collections to their active rows.

        ``_filter_query`` turns ``select_related`` into ``joinedload(attr)``, and
        the root WHERE clause never reaches the loaded relationship, so a retired
        child would still be emitted nested inside an active parent. Only
        collections are rewritten: scoping a required many-to-one parent would
        turn the relationship into ``None`` rather than filter it.

        :param select_related: The relationship attributes to eagerly load.
        :return: The same attributes, with retirable collections narrowed to
            their active rows.
        """
        scoped: list[Any] = []
        for attr in select_related:
            relationship = attr.property
            target = relationship.mapper.class_
            if relationship.uselist and issubclass(target, RetirableSQLModel):
                scoped.append(attr.and_(col(target.retired_at).is_(None)))
            else:
                scoped.append(attr)
        return scoped

    @classmethod
    def _retirement_statements(
        cls, entity_id: int, retired_at: datetime
    ) -> list[Update]:
        """Build the statements retiring an entity and its subtree, deepest first.

        Descendants retire before their ancestor so that even a torn write can
        only ever leave retired descendants under an active ancestor, never an
        active row under a retired one. The ``retired_at IS NULL`` guard replaces
        the manager injection these hand-built statements do not inherit, and is
        what leaves an already-retired row's original timestamp alone.

        :param entity_id: The primary key of the entity being retired.
        :param retired_at: The timestamp to stamp on every row retired here.
        :return: The UPDATE statements to run in order, in one transaction.
        """
        statements = [
            _retire(cls.Model, col(cls.Model.id) == entity_id, retired_at=retired_at)
        ]
        parent_ids: SelectOfScalar[int | None] = select(col(cls.Model.id)).where(
            col(cls.Model.id) == entity_id
        )
        for model, foreign_key in cls.retirement_subtree:
            parent_key = col(getattr(model, foreign_key))
            statements.append(
                _retire(model, parent_key.in_(parent_ids), retired_at=retired_at)
            )
            parent_ids = select(col(model.id)).where(parent_key.in_(parent_ids))
        statements.reverse()
        return statements

    @classmethod
    def _revival_statements(cls, entity_id: int) -> list[Update]:
        """Build the statements reviving an entity and its ancestors, topmost first.

        Revival is the mirror image of retirement: ancestors clear before their
        descendant, so a torn write cannot leave an active row under a retired
        ancestor. Siblings and descendants are left retired — a node coming back
        must not resurrect the services its upstream no longer reports.

        :param entity_id: The primary key of the entity being revived.
        :return: The UPDATE statements to run in order, in one transaction.
        """
        ancestors: list[Update] = []
        entity_ids: SelectOfScalar[int | None] = select(col(cls.Model.id)).where(
            col(cls.Model.id) == entity_id
        )
        manager = cls
        while issubclass(manager, BaseSQLModelChildManager):
            entity_ids = select(
                col(getattr(manager.Model, manager.connected_by))
            ).where(col(manager.Model.id).in_(entity_ids))
            parent_model = manager.ParentManager.Model
            ancestors.append(
                _revive(parent_model, col(parent_model.id).in_(entity_ids))
            )
            manager = manager.ParentManager
        ancestors.reverse()
        return [*ancestors, _revive(cls.Model, col(cls.Model.id) == entity_id)]

    @classmethod
    async def retire(cls, session: AsyncSession, instance: RetirableSQLModel) -> None:
        """Retire an entity and everything below it in one transaction.

        :param session: The asynchronous database session to use.
        :param instance: The entity to retire.
        """
        for statement in cls._retirement_statements(instance.id, utc_now()):
            await cls._exec(session, statement)
        await session.commit()

    @classmethod
    async def revive(cls, session: AsyncSession, instance: RetirableSQLModel) -> None:
        """Revive an entity and its retired ancestors in one transaction.

        :param session: The asynchronous database session to use.
        :param instance: The entity to revive.
        :raises HTTPConflictException: If an active row already holds the unique
            key the revived entity would reclaim.
        """
        try:
            for statement in cls._revival_statements(instance.id):
                await cls._exec(session, statement)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPConflictException(
                f"{cls.Model.__name__} cannot be revived: an active entity already "
                "holds its unique key."
            ) from None

    @classmethod
    async def collectible_ids(
        cls,
        session: AsyncSession,
        *,
        retired_before: datetime,
        keep_by_model: Mapping[type[RetirableSQLModel], Collection[int]],
        limit: int,
    ) -> list[int]:
        """Return the ids of this table's tombstones eligible for deletion.

        A tombstone is eligible when it aged past ``retired_before``, no caller
        declared it referenced, and nothing in its subtree is retained. Only
        reachable through the retired-inclusive subclasses: the default managers'
        ``retired_at IS NULL`` guard makes the underlying read match nothing.

        :param session: The asynchronous database session to use.
        :param retired_before: The cutoff a tombstone must predate.
        :param keep_by_model: The ids a caller declared still referenced, per table.
        :param limit: The most ids to return.
        :return: The eligible ids, lowest first.
        """
        whereclause = [
            col(cls.Model.retired_at).is_not(None),
            col(cls.Model.retired_at) < retired_before,
        ]
        if keep_ids := keep_by_model.get(cls.Model, ()):
            whereclause.append(col(cls.Model.id).not_in(keep_ids))
        if (
            pinned := _retained_descendant_exists(
                cls.retirement_subtree,
                col(cls.Model.id),
                retired_before,
                keep_by_model,
            )
        ) is not None:
            whereclause.append(~pinned)
        query = cls._filter_query(select(col(cls.Model.id)), *whereclause)
        result = await cls._exec(
            session, query.order_by(col(cls.Model.id)).limit(limit)
        )
        return list(result.all())

    @classmethod
    async def collect(cls, session: AsyncSession, entity_ids: Collection[int]) -> int:
        """Delete the named tombstones, leaving any active row among them alone.

        The ``retired_at IS NOT NULL`` filter is a guard, not an optimization: a
        caller that miscomputed its closure must not be able to hard-delete a
        live row through this method. An id that no longer exists simply matches
        nothing, so re-running an already-collected batch is a zero-row no-op.

        :param session: The asynchronous database session to use.
        :param entity_ids: The ids to delete.
        :return: The number of rows deleted.
        """
        if not entity_ids:
            return 0
        result = await cls.delete_where(
            session,
            col(cls.Model.id).in_(entity_ids),
            col(cls.Model.retired_at).is_not(None),
        )
        return result.rowcount


class NodeManager(RetirableManagerMixin, BaseSQLModelManager):
    """Manage Node operations, including retrieval, listing, and retirement.

    :ivar Model: The SQLModel class this manager is responsible for (`Node`).
    :cvar retirement_subtree: The descendants retiring a node cascades into.
    :cvar list_query_spec: The list-query spec declaring this entity's sortable
        allowlist, searchable columns, and default sort.
    """

    Model = Node
    retirement_subtree = (
        (Service, "node_id"),
        (Schema, "service_id"),
        (Table, "schema_id"),
    )
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(Node.name),
            "created_at": col(Node.created_at),
        },
        default_sort="name",
        tie_breaker=col(Node.id),
        searchable=[col(Node.name)],
    )


class ServiceManager(RetirableManagerMixin, BaseSQLModelChildManager):
    """Manage Service operations, including retrieval, listing, and retirement.

    :ivar Model: The SQLModel class this manager is responsible for (`Service`).
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`NodeManager`).
    :ivar connected_by: The field name that connects the child model to the parent
        model (`node_id`).
    :cvar retirement_subtree: The descendants retiring a service cascades into.
    :cvar list_query_spec: The list-query spec declaring this entity's sortable
        allowlist, searchable columns, and default sort.
    """

    Model = Service
    ParentManager = NodeManager
    connected_by = "node_id"
    retirement_subtree = ((Schema, "service_id"), (Table, "schema_id"))
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(Service.name),
            "created_at": col(Service.created_at),
        },
        default_sort="name",
        tie_breaker=col(Service.id),
        searchable=[col(Service.name)],
    )


class SchemaManager(RetirableManagerMixin, BaseSQLModelChildManager):
    """Manage Schema operations, including retrieval, listing, and retirement.

    :ivar Model: The SQLModel class this manager is responsible for (`Schema`).
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`ServiceManager`).
    :ivar connected_by: The field name that connects the child model to the parent
        model (`service_id`).
    :cvar retirement_subtree: The descendants retiring a schema cascades into.
    :cvar list_query_spec: The list-query spec declaring this entity's sortable
        allowlist, searchable columns, and default sort.
    """

    Model = Schema
    ParentManager = ServiceManager
    connected_by = "service_id"
    retirement_subtree = ((Table, "schema_id"),)
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(Schema.name),
            "created_at": col(Schema.created_at),
            "service_id": col(Schema.service_id),
        },
        default_sort="name",
        tie_breaker=col(Schema.id),
        searchable=[col(Schema.name)],
    )


class TableManager(RetirableManagerMixin, BaseSQLModelChildManager):
    """Manage Table operations, including retrieval, listing, and retirement.

    :ivar Model: The SQLModel class this manager is responsible for (`Table`).
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`SchemaManager`).
    :ivar connected_by: The field name that connects the child model to the parent
        model (`schema_id`).
    :cvar list_query_spec: The list-query spec declaring this entity's sortable
        allowlist, searchable columns, and default sort.
    """

    Model = Table
    ParentManager = SchemaManager
    connected_by = "schema_id"
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(Table.name),
            "created_at": col(Table.created_at),
            "schema_id": col(Table.schema_id),
        },
        default_sort="name",
        tie_breaker=col(Table.id),
        searchable=[col(Table.name)],
    )


class RetiredInclusiveNodeManager(NodeManager):
    """Read nodes without hiding the retired ones.

    :cvar include_retired: Always True, which is the whole point of the class.
    """

    include_retired = True


class RetiredInclusiveServiceManager(ServiceManager):
    """Read services without hiding the retired ones.

    :cvar include_retired: Always True, which is the whole point of the class.
    """

    include_retired = True


class RetiredInclusiveSchemaManager(SchemaManager):
    """Read schemas without hiding the retired ones.

    :cvar include_retired: Always True, which is the whole point of the class.
    """

    include_retired = True


class RetiredInclusiveTableManager(TableManager):
    """Read tables without hiding the retired ones.

    :cvar include_retired: Always True, which is the whole point of the class.
    """

    include_retired = True


#: The order collection walks the retirable entities in, deepest first, paired
#: with the entity name SEP addresses each type by. Deleting a descendant before
#: its ancestor mirrors :meth:`RetirableManagerMixin._retirement_statements`, so
#: an interrupted run can only ever leave deleted descendants under a surviving
#: ancestor — never an orphan, and never a live row beneath a deleted ancestor.
COLLECTION_ORDER: tuple[
    tuple[RetirableEntityName, type[RetirableManagerMixin]], ...
] = (
    (RetirableEntityName.TABLE, RetiredInclusiveTableManager),
    (RetirableEntityName.SCHEMA, RetiredInclusiveSchemaManager),
    (RetirableEntityName.SERVICE, RetiredInclusiveServiceManager),
    (RetirableEntityName.NODE, RetiredInclusiveNodeManager),
)


class HostSystemObservationManager(BaseSQLModelChildManager):
    """Manage host system observation operations.

    :ivar Model: The SQLModel class this manager is responsible for
        (`HostSystemObservation`).
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`NodeManager`).
    :ivar connected_by: The field name that connects the child model to the parent
        model (`node_id`).
    """

    Model = HostSystemObservation
    ParentManager = NodeManager
    connected_by = "node_id"


class ServiceSystemObservationManager(BaseSQLModelChildManager):
    """Manage service system observation operations.

    :ivar Model: The SQLModel class this manager is responsible for
        (`ServiceSystemObservation`).
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`ServiceManager`).
    :ivar connected_by: The field name that connects the child model to the parent
        model (`service_id`).
    """

    Model = ServiceSystemObservation
    ParentManager = ServiceManager
    connected_by = "service_id"
