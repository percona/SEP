"""Define database operations."""

import logging
from collections.abc import Sequence
from typing import Any
from typing import Type
from typing import TypeVar

from sqlalchemy import ScalarResult
from sqlalchemy.engine import TupleResult
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql._typing import _ColumnExpressionArgument
from sqlmodel import select
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql._expression_select_cls import Select
from sqlmodel.sql._expression_select_cls import SelectOfScalar

from app.api.exceptions import HTTPNotFoundException

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SQLModel)


class BaseManager:
    """Manage database operations for a SQLModel-based model.

    Attributes
    ----------
    Model : Type[T]
        The SQLModel class for which this manager handles operations.

    """

    Model: Type[T]

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
        return await cls._exec(session, query)

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

    # TODO: Different methods for save/update with validation models
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
        await session.commit()
        await session.refresh(instance)
        return instance

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
