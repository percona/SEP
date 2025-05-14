"""Define database operations."""

import logging
from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import CursorResult, delete, func, inspect, ScalarResult, Select
from sqlalchemy.engine import TupleResult
from sqlalchemy.exc import DatabaseError, NoResultFound
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql import ColumnExpressionArgument
from sqlalchemy.sql.dml import DMLWhereBase
from sqlmodel import col, select, SQLModel, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import BaseSQLModel
from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPNotFoundException,
)

logger = logging.getLogger(__name__)

Whereable = Select | DMLWhereBase
W = TypeVar("W", bound=Whereable)
T = TypeVar("T")
B = TypeVar("B", bound=BaseSQLModel)
S = TypeVar("S", bound=SQLModel)
P = TypeVar("P", bound=BaseModel)
M = TypeVar("M", bound="BaseSQLModelManager")


class BaseManager:
    """Manage database operations for a SQLAlchemy model.

    :param Model: The SQLAlchemy class for which this manager handles operations.
    :type Model: type[T]
    """

    Model: type[T]

    @classmethod
    def _construct_instance(cls, instance_create: P, **extra_fields: Any) -> T:
        instance_data = {
            **instance_create.model_dump(include=cls.Model.__table__.columns.keys()),
            **extra_fields,
        }
        return cls.Model(**instance_data)

    @classmethod
    def _filter_query(
        cls,
        query: W,
        *whereclause: ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> W:
        for clause in whereclause:
            query = query.where(clause)
        for field_name, value in equal_filters.items():
            if value is None:
                logger.debug(
                    "Field %s has no value and will be ignored. Use %s.%s.is_(None) to check for null values.",
                    field_name,
                    cls.Model.__name__,
                    field_name,
                )
                continue
            query = query.where(col(getattr(cls.Model, field_name)) == value)
        if select_related:
            query = query.options(*[joinedload(attr) for attr in select_related])
        return query

    @classmethod
    def _build_query(
        cls,
        *whereclause: ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> W:
        query = select(cls.Model)
        return cls._filter_query(
            query,
            *whereclause,
            select_related=select_related,
            **equal_filters,
        )

    @classmethod
    async def _exec(
        cls,
        session: AsyncSession,
        query: W,
    ) -> TupleResult | ScalarResult | CursorResult:
        logger.debug("Executing query: %s", query)
        return await session.exec(query)

    @classmethod
    async def _select(
        cls,
        session: AsyncSession,
        *whereclause: ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> TupleResult | ScalarResult:
        query = cls._build_query(
            *whereclause,
            select_related=select_related,
            **equal_filters,
        )
        result = await cls._exec(session, query)
        return result.unique()

    @classmethod
    async def values_list(
        cls,
        session: AsyncSession,
        fields: Sequence[str],
        *whereclause: ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> list[Any]:
        """Return a list of values for the specified fields.

        This method retrieves values for the specified fields from the database. If no
        fields are provided, it retrieves all values for the model in alphabetical
        order.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param fields: The fields to retrieve values for.
        :type fields: Sequence[str]
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: ColumnExpressionArgument[bool]
        :param select_related: Fields to be loaded using `joinedload` for related
            objects.
        :type select_related: Sequence
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        :return: A list of tuples containing the values for the specified fields, or
            a flat list of values if only one field is specified.
        :rtype: list[Any]
        """
        if not fields:
            items = await cls.list(
                session, *whereclause, select_related=select_related, **equal_filters
            )
            return [
                tuple(field[1] for field in sorted(item, key=lambda field: field[0]))
                for item in items
            ]
        query = cls._filter_query(
            select(*(getattr(cls.Model, field) for field in fields)),
            *whereclause,
            select_related=select_related,
            **equal_filters,
        )
        result = await cls._exec(session, query)
        return list(result.all())

    @classmethod
    async def list(
        cls,
        session: AsyncSession,
        *whereclause: ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> list[T]:
        """Return a list of all records that match the query.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: ColumnExpressionArgument[bool]
        :param select_related: Fields to be loaded using `joinedload` for related
            objects.
        :type select_related: Sequence
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        :return: A list of matching records.
        :rtype: list[T]
        """
        # TODO: Pagination  # noqa: TD002, TD003
        result = await cls._select(
            session,
            *whereclause,
            select_related=select_related,
            **equal_filters,
        )
        return list(result.all())

    @classmethod
    async def first(
        cls,
        session: AsyncSession,
        *whereclause: ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> T | None:
        """Return the first record that matches the query.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: ColumnExpressionArgument[bool]
        :param select_related: Fields to be loaded using `joinedload` for related
            objects.
        :type select_related: Sequence
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        :return: The first matching record, or None if no match is found.
        :rtype: T | None
        """
        result = await cls._select(
            session,
            *whereclause,
            select_related=select_related,
            **equal_filters,
        )
        return result.first()

    @classmethod
    async def get(
        cls,
        session: AsyncSession,
        *whereclause: ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> T:
        """Return the single record that matches the query.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: ColumnExpressionArgument[bool]
        :param select_related: Fields to be loaded using `joinedload` for related
            objects.
        :type select_related: Sequence
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        :return: The matching record.
        :rtype: T
        :raises NoResultFound: If no record is found that matches the query.
        """
        result = await cls._select(
            session,
            *whereclause,
            select_related=select_related,
            **equal_filters,
        )
        return result.one()

    @classmethod
    async def get_or_404(
        cls,
        session: AsyncSession,
        *whereclause: ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> T:
        """Return the single record that matches the query, or raise a 404 error.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: ColumnExpressionArgument[bool]
        :param select_related: Fields to be loaded using `joinedload` for related
            objects.
        :type select_related: Sequence
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        :return: The matching record.
        :rtype: T
        :raises HTTPNotFoundException: If no record is found that matches the query.
        """
        try:
            return await cls.get(
                session,
                *whereclause,
                select_related=select_related,
                **equal_filters,
            )
        except NoResultFound:
            raise HTTPNotFoundException from None

    @classmethod
    async def save_batch(
        cls,
        session: AsyncSession,
        *instances: T,
        flag_modified_fields: Sequence[str] = (),
    ) -> tuple[T, ...]:
        """Save multiple instances of a model to the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instances: The model instances to be saved.
        :type instances: T
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The saved instances.
        :rtype: tuple[T, ...]
        """
        for instance in instances:
            for field in flag_modified_fields:
                flag_modified(instance, field)
            session.add(instance)
        await session.commit()
        return instances

    @classmethod
    async def save(
        cls,
        session: AsyncSession,
        instance: T,
        *,
        flag_modified_fields: Sequence[str] = (),
    ) -> T:
        """Save a model instance to the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance: The model instance to be saved.
        :type instance: T
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The saved instance.
        :rtype: T
        :raises HTTPBadRequestException: If a DatabaseError occurs during commit.
        """
        for field in flag_modified_fields:
            flag_modified(instance, field)
        session.add(instance)
        try:
            await session.commit()
        except DatabaseError:
            logger.exception("DatabaseError saving instance %s", instance)
            raise HTTPBadRequestException from None
        else:
            logger.debug("Saved instance of %s: %s", cls.Model.__name__, instance)
        await session.refresh(instance)
        return instance

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        instance_create: P,
        **extra_fields: Any,
    ) -> T:
        """Create and save a new model instance in the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_create: The data used to create the new model instance.
        :type instance_create: P
        :param extra_fields: Additional fields to be set on the model instance.
        :type extra_fields: Any
        :return: The newly created and saved instance.
        :rtype: T
        """
        instance = cls._construct_instance(instance_create, **extra_fields)
        logger.debug("Creating new instance of %s: %s", cls.Model.__name__, instance)
        return await cls.save(session, instance)

    @classmethod
    async def get_or_create(
        cls,
        session: AsyncSession,
        instance_create: P,
        filter_include: set[str] | None = None,
        **extra_fields: Any,
    ) -> tuple[T, bool]:
        """Retrieve an existing model instance or create a new one if none exists.

        This method attempts to find an instance of `cls.Model` with the fields defined
        in `instance_create` and (optionally) specified in `filter_include`. If such an
        instance exists, it returns it. Otherwise, it creates and saves a new one.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_create: The data used to filter and possibly create the
            instance.
        :type instance_create: P
        :param filter_include: The set of fields of `instance_create` to be included in
            the search filter. Use None (default) for all fields.
        :param extra_fields: Additional fields to be set on the created instance.
        :type extra_fields: Any
        :return: The existing or newly created instance of `cls.Model`, and a bool
            specifying whether a new instance was created.
        :rtype: tuple[T, bool]
        """
        existent_instance = await cls.first(
            session, **instance_create.model_dump(include=filter_include)
        )
        if existent_instance:
            return existent_instance, False
        return await cls.create(session, instance_create, **extra_fields), True

    @classmethod
    async def update(
        cls,
        session: AsyncSession,
        existing_instance: T,
        updated_instance: P,
        *,
        flag_modified_fields: Sequence[str] = (),
    ) -> T:
        """Update an existing model instance with new data and save it.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param existing_instance: The existing model instance to be updated.
        :type existing_instance: T
        :param updated_instance: The new data to update the model instance with.
        :type updated_instance: P
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The updated and saved instance.
        :rtype: T
        """
        logger.debug(
            "Updating existing instance of %s (%s): %s",
            cls.Model.__name__,
            existing_instance.id,
            updated_instance,
        )
        for key, value in updated_instance.model_dump(
            include=cls.Model.__table__.columns.keys()
        ).items():
            setattr(existing_instance, key, value)
        return await cls.save(
            session,
            existing_instance,
            flag_modified_fields=flag_modified_fields,
        )

    @classmethod
    async def update_where(
        cls,
        session: AsyncSession,
        values: dict[str, Any],
        *whereclause: ColumnExpressionArgument[bool],
        **equal_filters: Any,
    ) -> CursorResult:
        """Execute an UPDATE statement.

        This method executes an UPDATE statement to update specific values for rows
        matching the specified filters.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param values: A dict with column names as keys and values as values.
        :type values: dict[str, Any]
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: ColumnExpressionArgument[bool]
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        :return: The result of the UPDATE statement execution.
        :rtype: CursorResult
        """
        if not whereclause and not equal_filters:
            raise ValueError(
                "You must specify at least one filter in *whereclause or **equal_filters"
            )
        query = cls._filter_query(
            update(cls.Model), *whereclause, **equal_filters
        ).values(**values)
        result = await cls._exec(session, query)
        await session.commit()
        logger.debug(
            "Updated %s instances of %s with values %s",
            result.rowcount,
            cls.Model.__name__,
            values,
        )
        return result

    @classmethod
    async def delete(cls, session: AsyncSession, instance: T) -> T:
        """Delete a model instance from the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance: The model instance to be deleted.
        :type instance: T
        :return: The deleted instance.
        :rtype: T
        """
        await session.delete(instance)
        await session.commit()
        return instance

    @classmethod
    async def delete_where(
        cls,
        session: AsyncSession,
        *whereclause: ColumnExpressionArgument[bool],
        **equal_filters: Any,
    ) -> CursorResult:
        """Execute a DELETE statement.

        This method executes a DELETE statement to delete specific rows matching the
        specified filters.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: ColumnExpressionArgument[bool]
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        :return: The result of the DELETE statement execution.
        :rtype: CursorResult
        """
        if not whereclause and not equal_filters:
            raise ValueError(
                "You must specify at least one filter in *whereclause or **equal_filters"
            )
        query = cls._filter_query(delete(cls.Model), *whereclause, **equal_filters)
        result = await cls._exec(session, query)
        await session.commit()
        logger.debug(
            "Deleted %s instances of %s",
            result.rowcount,
            cls.Model.__name__,
        )
        return result

    @classmethod
    async def count(
        cls,
        session: AsyncSession,
        *whereclause: ColumnExpressionArgument[bool],
        **equal_filters: Any,
    ) -> int:
        """Return the count of records that match the query.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: ColumnExpressionArgument[bool]
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        :return: The count of matching records.
        :rtype: int
        """
        query = cls._filter_query(
            select(func.count()).select_from(cls.Model), *whereclause, **equal_filters
        )
        result = await session.scalar(query)
        return result or 0


class BaseSQLModelManager(BaseManager):
    """Manage database operations for a BaseSQLModel-based model.

    :param Model: The BaseSQLModel class for which this manager handles operations.
    :type Model: type[B]
    """

    Model: type[B]

    @classmethod
    def _construct_instance(cls, instance_create: S, **extra_fields: Any) -> B:
        pk_column = inspect(cls.Model).primary_key[0]
        if pk_column.autoincrement and isinstance(
            None,
            cls.Model.model_fields[pk_column.name].annotation,
        ):
            extra_fields[pk_column.name] = None
        return cls.Model.model_validate(instance_create, update=extra_fields)

    @classmethod
    async def save(
        cls,
        session: AsyncSession,
        instance: T,
        *,
        flag_modified_fields: Sequence[str] = (),
    ) -> T:
        """Save a model instance to the database.

        This method overrides `BaseManager.save()` to check for duplicate errors for
        each unique index of the Model.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance: The model instance to be saved.
        :type instance: T
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The saved instance.
        :rtype: T
        :raises HTTPConflictException: If saving the instance would cause a duplicate
            entry database error.
        :raises HTTPBadRequestException: If a DatabaseError occurs during commit.
        """
        for index in inspect(cls.Model).local_table.indexes:
            if index.unique:
                equal_filters = {
                    column.name: getattr(instance, column.name, None)
                    for column in index.columns
                }
                if all(equal_filters.values()):
                    duplicate = await cls.first(
                        session, col(cls.Model.id) != instance.id, **equal_filters
                    )
                    if duplicate is not None:
                        raise HTTPConflictException(
                            f"{cls.Model.__name__} with the same {', '.join(equal_filters)} already exists."
                        )
        return await super().save(
            session, instance, flag_modified_fields=flag_modified_fields
        )

    @classmethod
    async def update(
        cls,
        session: AsyncSession,
        existing_instance: B,
        updated_instance: S,
        *,
        flag_modified_fields: Sequence[str] = (),
    ) -> B:
        """Update an existing model instance with new data and save it.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param existing_instance: The existing model instance to be updated.
        :type existing_instance: B
        :param updated_instance: The new data to update the model instance with.
        :type updated_instance: S
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The updated and saved instance.
        :rtype: B
        """
        logger.debug(
            "Updating existing instance of %s (%s): %s",
            cls.Model.__name__,
            existing_instance.id,
            updated_instance,
        )
        updated_instance_data = updated_instance.model_dump(exclude_unset=True)
        existing_instance.sqlmodel_update(updated_instance_data)
        return await cls.save(
            session,
            existing_instance,
            flag_modified_fields=flag_modified_fields,
        )


class BaseSQLModelChildManager(BaseSQLModelManager):
    """Manage database operations for child models with a parent association.

    :param ParentManager: The manager class responsible for handling the parent model.
    :type ParentManager: type[M]
    :param connected_by: The field name that connects the child model to the parent
        model.
    :type connected_by: str
    """

    ParentManager: type[M]
    connected_by: str

    @classmethod
    async def update(
        cls,
        session: AsyncSession,
        existing_instance: T,
        updated_instance: P,
        *,
        flag_modified_fields: Sequence[str] = (),
    ) -> T:
        """Update an existing child model instance, ensuring parent association.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param existing_instance: The existing child model instance to be updated.
        :type existing_instance: T
        :param updated_instance: The new data to update the child model instance with.
        :type updated_instance: P
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The updated and saved child instance.
        :rtype: T
        :raises HTTPBadRequestException: If the associated parent instance does not
            exist.
        """
        parent_id = getattr(updated_instance, cls.connected_by, None)
        try:
            await cls.ParentManager.get(session, id=parent_id)
        except NoResultFound:
            raise HTTPBadRequestException(
                f"Invalid {cls.connected_by}: {parent_id}",
            ) from None
        return await super().update(
            session,
            existing_instance,
            updated_instance,
            flag_modified_fields=flag_modified_fields,
        )
