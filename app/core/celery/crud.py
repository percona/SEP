"""Define database operations for the Celery scheduler."""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel
from sqlalchemy_celery_beat import CrontabSchedule, IntervalSchedule, PeriodicTask
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseManager


class IntervalScheduleManager(BaseManager):
    """Manage IntervalSchedule operations.

    :ivar Model: The SQLAlchemy class this manager is responsible for
        (`IntervalSchedule`).
    :vartype Model: type[IntervalSchedule]
    """

    Model = IntervalSchedule


class CrontabScheduleManager(BaseManager):
    """Manage CrontabSchedule operations.

    :ivar Model: The SQLAlchemy class this manager is responsible for
        (`CrontabSchedule`).
    :vartype Model: type[CrontabSchedule]
    """

    Model = CrontabSchedule


class BasePeriodicTaskManager(BaseManager):
    """Manage PeriodicTask operations.

    :ivar Model: The SQLAlchemy class this manager is responsible for
        (`PeriodicTask`).
    :vartype Model: type[PeriodicTask]
    """

    Model = PeriodicTask

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        instance_create: BaseModel,
        **extra_fields: Any,
    ) -> PeriodicTask:
        """Create and save a new PeriodicTask, creating the necessary scheduler with it.

        This method overrides `BaseManager.create()` to create the associated
        IntervalSchedule or CrontabSchedule object if needed.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_create: The data used to create the new model instance.
        :type instance_create: BaseModel
        :param extra_fields: Additional fields to be set on the model instance.
        :type extra_fields: Any
        :return: The newly created and saved instance.
        :rtype: PeriodicTask
        """
        if instance_create.interval is not None:
            (
                extra_fields["schedule_model"],
                _,
            ) = await IntervalScheduleManager.get_or_create(
                session, instance_create.interval
            )
        else:
            (
                extra_fields["schedule_model"],
                _,
            ) = await CrontabScheduleManager.get_or_create(
                session, instance_create.crontab
            )
        return await super().create(session, instance_create, **extra_fields)

    @classmethod
    async def update(
        cls,
        session: AsyncSession,
        existing_instance: PeriodicTask,
        updated_instance: BaseModel,
        *,
        flag_modified_fields: Sequence[str] = (),
    ) -> PeriodicTask:
        """Update and save a PeriodicTask, creating the necessary scheduler with it.

        This method overrides `BaseManager.update()` to create the associated
        IntervalSchedule or CrontabSchedule object if needed.

        :param session: The SQLAlchemy asynchronous session to use for database operations.
        :type session: AsyncSession
        :param existing_instance: The existing model instance to be updated.
        :type existing_instance: PeriodicTask
        :param updated_instance: The new data to update the model instance with.
        :type updated_instance: BaseModel
        :param flag_modified_fields: Fields to be flagged as modified before saving.
        :type flag_modified_fields: Sequence[str]
        :return: The updated and saved instance.
        :rtype: PeriodicTask
        """
        if updated_instance.interval is not None:
            (
                existing_instance.schedule_model,
                _,
            ) = await IntervalScheduleManager.get_or_create(
                session, updated_instance.interval
            )
        else:
            (
                existing_instance.schedule_model,
                _,
            ) = await CrontabScheduleManager.get_or_create(
                session, updated_instance.crontab
            )
        return await super().update(
            session,
            existing_instance,
            updated_instance,
            flag_modified_fields=flag_modified_fields,
        )
