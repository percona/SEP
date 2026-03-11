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

from fastapi import APIRouter

from app.api.deps import CurrentUser, IsAdminDep
from app.core.auth.exceptions import HTTPForbiddenException
from app.core.auth.utils import get_user_model

logger = logging.getLogger(__name__)

router = APIRouter()

User = get_user_model()


@router.get("/", dependencies=[IsAdminDep])
async def list_users() -> list[User]:
    """List users.

    :return: The list of users.
    :rtype: list[User]
    """
    return await User.get_users()


@router.get("/me")
async def retrieve_current_user(current_user: CurrentUser) -> User:
    """Retrieve the current authenticated user.

    :param current_user: The current authenticated user.
    :type current_user: CurrentUser
    :return: The current authenticated user.
    :rtype: User
    """
    return current_user


@router.get("/{username}")
async def retrieve_user(current_user: CurrentUser, username: str) -> User:
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
