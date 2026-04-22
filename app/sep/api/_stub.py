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

"""Register a placeholder sub-router that validates plugin API composition.

Stand in for real plugin routers until the first one is migrated under the
shared ``/api/plugins/`` prefix. Remove this module once a real plugin sub-
router is registered on ``plugins_router``.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def stub() -> dict[str, bool]:
    """Return a trivial payload confirming router composition and auth.

    :return: A fixed success payload.
    :rtype: dict[str, bool]
    """
    return {"ok": True}
