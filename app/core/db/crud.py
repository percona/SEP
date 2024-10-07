"""Define database operations."""

import logging
from collections.abc import Sequence
from typing import Any
from typing import TypeVar

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

    Attributes
    ----------
    Model : Type[T]
        The BaseSQLModel class for which this manager handles operations.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for query execution.
        whereclause : _ColumnExpressionArgument[bool], optional
            SQL expressions for the `where` clause of the query.
        select_related : Sequence, optional
            Fields to be loaded using `joinedload` for related objects.
        equal_filters : dict, optional
            Keyword arguments representing column names and their respective filter
            values.

        Returns
        -------
        list[T]
            A list of matching records.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for query execution.
        whereclause : _ColumnExpressionArgument[bool], optional
            SQL expressions for the `where` clause of the query.
        select_related : Sequence, optional
            Fields to be loaded using `joinedload` for related objects.
        equal_filters : dict, optional
            Keyword arguments representing column names and their respective filter
            values.

        Returns
        -------
        T or None
            The first matching record, or None if no match is found.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for query execution.
        whereclause : _ColumnExpressionArgument[bool], optional
            SQL expressions for the `where` clause of the query.
        select_related : Sequence, optional
            Fields to be loaded using `joinedload` for related objects.
        equal_filters : dict, optional
            Keyword arguments representing column names and their respective filter
            values.

        Returns
        -------
        T
            The matching record.

        Raises
        ------
        NoResultFound
            If no record is found that matches the query.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for query execution.
        whereclause : _ColumnExpressionArgument[bool], optional
            SQL expressions for the `where` clause of the query.
        select_related : Sequence, optional
            Fields to be loaded using `joinedload` for related objects.
        equal_filters : dict, optional
            Keyword arguments representing column names and their respective filter
            values.

        Returns
        -------
        T
            The matching record.

        Raises
        ------
        HTTPNotFoundException
            If no record is found that matches the query.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        instances : T
            The model instances to be saved.
        flag_modified_fields : Sequence[str], optional
            Fields to be flagged as modified before saving.

        Returns
        -------
        Sequence[T]
            The saved instances.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        instance : T
            The model instance to be saved.
        flag_modified_fields : Sequence[str], optional
            Fields to be flagged as modified before saving.

        Returns
        -------
        T
            The saved instance.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        instance_create : S
            The data used to create the new model instance.
        **extra_fields : Any
            Additional fields to be set on the model instance.

        Returns
        -------
        T
            The newly created and saved instance.

        """
        extra_fields["id"] = None
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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        existing_instance : T
            The existing model instance to be updated.
        updated_instance : S
            The new data to update the model instance with.
        flag_modified_fields : Sequence[str], optional
            Fields to be flagged as modified before saving.

        Returns
        -------
        T
            The updated and saved instance.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        instance : T
            The model instance to be deleted.

        Returns
        -------
        T
            The deleted instance.

        """
        await session.delete(instance)
        await session.commit()
        return instance


M = TypeVar("M", bound="BaseManager")


class BaseChildManager(BaseManager):
    """Manage database operations for child models with a parent association.

    Attributes
    ----------
    ParentManager : Type[M]
        The manager class responsible for handling the parent model.
    connected_by : str
        The field name that connects the child model to the parent model.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        existing_instance : T
            The existing child model instance to be updated.
        updated_instance : S
            The new data to update the child model instance with.
        flag_modified_fields : Sequence[str], optional
            Fields to be flagged as modified before saving.

        Returns
        -------
        T
            The updated and saved child instance.

        Raises
        ------
        HTTPBadRequestException
            If the associated parent instance does not exist.

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
