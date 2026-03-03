# Copyright 2025 Percona LLC
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

"""Define database operations for Snippets."""

from typing import Any

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseSQLModelManager
from app.sep.snippets.models import Snippet


class SnippetManager(BaseSQLModelManager):
    """Manage Snippet operations, including retrieval, listing, and deletion.

    :cvar Model: The SQLModel class this manager is responsible for (`Snippet`).
    :vartype Model: type[Snippet]
    :cvar ordering: The default ordering for listing snippets, first by `approved_at`
        in descending order, then by `created_at`.
    :vartype ordering: list[ColumnExpressionOrStrLabelArgument]
    """

    Model = Snippet
    ordering = [col(Snippet.approved_at).desc(), "created_at"]

    @classmethod
    async def get_or_create(
        cls,
        session: AsyncSession,
        instance_create: Snippet,
        filter_include: set[str] | None = None,
        **extra_fields: Any,
    ) -> tuple[Snippet, bool]:
        """Retrieve an existing Snippet instance or create a new one if none exists.

        This method overrides the default `get_or_create` method to generate the `meta`
        field of the Snippet instance based on the snippet's path.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_create: The data used to filter and possibly create the
            instance.
        :type instance_create: Snippet
        :param filter_include: The set of fields of `instance_create` to be included in
            the search filter. Use None (default) for all fields.
        :param extra_fields: Additional fields to be set on the created instance.
        :type extra_fields: Any
        :return: The existing or newly created instance of `cls.Model`, and a bool
            specifying whether a new instance was created.
        :rtype: tuple[Snippet, bool]
        """
        existent_instance = await cls.first(
            session, **instance_create.model_dump(include=filter_include)
        )
        if existent_instance:
            return existent_instance, False
        await instance_create.update_meta()
        return await cls.create(session, instance_create, **extra_fields), True
