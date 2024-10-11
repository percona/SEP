"""Define database operations."""

import logging
from collections.abc import Sequence
from typing import Any
from typing import TypeVar

from sqlalchemy import inspect
from sqlalchemy import ScalarResult
from sqlalchemy.engine import TupleResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql._typing import _ColumnExpressionArgument
from sqlmodel import select
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql._expression_select_cls import Select
from sqlmodel.sql._expression_select_cls import SelectOfScalar

from app.api.exceptions import HTTPBadRequestException
from app.api.exceptions import HTTPConflictException
from app.api.exceptions import HTTPNotFoundException
from app.core.db import BaseSQLModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseSQLModel)
S = TypeVar("S", bound=SQLModel)


class BaseManager:
    """Manage database operations for a BaseSQLModel-based model.

    :param Model: The BaseSQLModel class for which this manager handles operations.
    :type Model: type[T]
    """

    Model: type[T]

    @classmethod
    def _filter_query(
        cls,
        query: Select | SelectOfScalar,
        *whereclause: _ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> Select | SelectOfScalar:
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
            query = query.where(getattr(cls.Model, field_name) == value)
        if select_related:
            query = query.options(*[joinedload(attr) for attr in select_related])
        return query

    @classmethod
    def _build_query(
        cls,
        *whereclause: _ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> Select | SelectOfScalar:
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
        query: Select | SelectOfScalar,
    ) -> TupleResult | ScalarResult:
        logger.debug("Executing select query: %s", query)
        return await session.exec(query)

    @classmethod
    async def _select(
        cls,
        session: AsyncSession,
        *whereclause: _ColumnExpressionArgument[bool],
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
    async def list(
        cls,
        session: AsyncSession,
        *whereclause: _ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> list[T]:
        """Return a list of all records that match the query.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: _ColumnExpressionArgument[bool]
        :param select_related: Fields to be loaded using `joinedload` for related
            objects.
        :type select_related: Sequence
        :param equal_filters: Keyword arguments representing column names and their
            respective filter values.
        :type equal_filters: Any
        :return: A list of matching records.
        :rtype: list[T]
        """
        # TODO: Pagination
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
        *whereclause: _ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> T | None:
        """Return the first record that matches the query.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: _ColumnExpressionArgument[bool]
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
        *whereclause: _ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> T:
        """Return the single record that matches the query.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: _ColumnExpressionArgument[bool]
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
        *whereclause: _ColumnExpressionArgument[bool],
        select_related: Sequence = (),
        **equal_filters: Any,
    ) -> T:
        """Return the single record that matches the query, or raise a 404 error.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :type session: AsyncSession
        :param whereclause: SQL expressions for the `where` clause of the query.
        :type whereclause: _ColumnExpressionArgument[bool]
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
    ) -> Sequence[T]:
        """Save multiple instances of a model to the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instances: The model instances to be saved.
        :type instances: T
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The saved instances.
        :rtype: Sequence[T]
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
        :raises HTTPConflictException: If an integrity error occurs during commit.
        """
        for field in flag_modified_fields:
            flag_modified(instance, field)
        session.add(instance)
        try:
            await session.commit()
        except IntegrityError as exc:
            logger.debug("IntegrityError saving instance %s", instance, exc_info=True)
            raise HTTPConflictException(
                exc.args[0],
            ) from None  # TODO: Improve error message
        await session.refresh(instance)
        return instance

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        instance_create: S,
        **extra_fields: Any,
    ) -> T:
        """Create and save a new model instance in the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_create: The data used to create the new model instance.
        :type instance_create: S
        :param extra_fields: Additional fields to be set on the model instance.
        :type extra_fields: Any
        :return: The newly created and saved instance.
        :rtype: T
        """
        pk_column = inspect(cls.Model).primary_key[0]
        if pk_column.autoincrement and isinstance(
            None,
            cls.Model.model_fields[pk_column.name].annotation,
        ):
            extra_fields[pk_column.name] = None
        instance = cls.Model.model_validate(instance_create, update=extra_fields)
        return await cls.save(session, instance)

    @classmethod
    async def update(
        cls,
        session: AsyncSession,
        existing_instance: T,
        updated_instance: S,
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
        :type updated_instance: S
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The updated and saved instance.
        :rtype: T
        """
        updated_instance_data = updated_instance.model_dump(exclude_unset=True)
        existing_instance.sqlmodel_update(updated_instance_data)
        return await cls.save(
            session,
            existing_instance,
            flag_modified_fields=flag_modified_fields,
        )

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


M = TypeVar("M", bound="BaseManager")


class BaseChildManager(BaseManager):
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
        updated_instance: S,
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
        :type updated_instance: S
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
