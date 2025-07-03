# Copyright (C) 2025 Percona LLC
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

"""Define utilities for handling lists."""

__all__ = ["remove_duplicates"]


def remove_duplicates(v: list) -> list:
    """Remove duplicates from a list while maintaining order.

    :param v: The list to remove duplicates from.
    :type v: list
    :return: The list without duplicates.
    :rtype: list
    """
    unique_list = []
    for item in v:
        if item not in unique_list:
            unique_list.append(item)
    return unique_list
