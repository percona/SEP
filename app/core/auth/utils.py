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

"""Define auth utility functions."""

from app.core.auth.models import BaseUser
from app.core.config import settings
from app.core.utils import import_var


def get_user_model() -> type[BaseUser]:
    """Retrieve the user model class as defined in the settings.

    This function dynamically imports and returns the user model specified in
    the `settings.AUTH_USER_MODEL` configuration. If no custom user model is
    specified, it returns the `BaseUser` model by default.

    :return: The user model class, should be a subclass of `BaseUser`.
    :rtype: type[BaseUser]
    :raises ImportError: If the module specified in `settings.AUTH_USER_MODEL`
        cannot be imported.
    :raises AttributeError: If the model class specified in `settings.AUTH_USER_MODEL`
        cannot be found in the imported module.
    """
    return import_var(settings.AUTH_USER_MODEL)
