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

"""Shared offset/limit pagination models, helpers, and FastAPI dependencies."""

from app.core.pagination.deps import (
    make_pagination_dep,
    pagination_dep,
    PaginationDep,
    PaginationDependency,
)
from app.core.pagination.models import (
    DEFAULT_PAGINATION_LIMIT,
    DEFAULT_PAGINATION_OFFSET,
    fetch_all_dict_items,
    fetch_all_items,
    MAX_PAGINATION_LIMIT,
    PaginatedDictPage,
    PaginatedResponse,
    Pagination,
)

__all__ = [
    "DEFAULT_PAGINATION_LIMIT",
    "DEFAULT_PAGINATION_OFFSET",
    "MAX_PAGINATION_LIMIT",
    "PaginatedDictPage",
    "PaginatedResponse",
    "Pagination",
    "PaginationDep",
    "PaginationDependency",
    "fetch_all_dict_items",
    "fetch_all_items",
    "make_pagination_dep",
    "pagination_dep",
]
