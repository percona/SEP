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

"""Define the API routes for User actions."""

import logging
from collections.abc import Sequence

from fastapi import APIRouter

from app.api.deps import CurrentUser, IsAdminDep
from app.core.auth.exceptions import HTTPForbiddenException
from app.core.auth.models import BaseUser
from app.core.auth.utils import get_user_model

logger = logging.getLogger(__name__)

router = APIRouter()

User = get_user_model()


# pagination-ok: the provider SDK returns the whole organization in one call
# (Casdoor /api/get-users, Grafana /api/org/users), so there is no upstream
# window to page against; the cardinality is the operator's own user count.
@router.get(
    "/",
    dependencies=[IsAdminDep],
    response_model=list[User],  # ty: ignore[invalid-type-form]
)
async def list_users() -> Sequence[BaseUser]:
    """List users.

    :return: The list of users.
    """
    return await User.get_users()


@router.get("/me", response_model=User)
async def retrieve_current_user(current_user: CurrentUser) -> BaseUser:
    """Retrieve the current authenticated user.

    :param current_user: The current authenticated user.
    :type current_user: CurrentUser
    :return: The current authenticated user.
    :rtype: User
    """
    return current_user


@router.get("/{username}", response_model=User)
async def retrieve_user(current_user: CurrentUser, username: str) -> BaseUser:
    """Retrieve a user by username.

    :param current_user: The current authenticated user.
    :type current_user: CurrentUser
    :param username: The username of the user to retrieve.
    :type username: str
    :return: The requested user.
    :rtype: User
    :raises HTTPForbiddenException: If the current user is not an admin and tries to
        access another user's information.
    """
    if current_user.username == username:
        return current_user
    if not current_user.is_admin:
        raise HTTPForbiddenException
    return await User.get_user(username)
