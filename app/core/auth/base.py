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

"""Define the base authentication-provider interface."""

from abc import ABC
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import ClassVar

from app.core.auth.models import BaseTokenPayload, BaseUser


class BaseAuthProvider(ABC):
    """Compose the models and lifecycle of an authentication provider.

    A concrete provider subclasses its configuration-bearing model (typically a
    ``RemoteAPI`` SDK) first and this mixin second, so the provider *is* its SDK
    and its config maps flat onto the SDK fields. It declares the user and token
    models it serves via the two class variables below, which the auth seam
    (``get_user_model`` / ``get_token_payload_model``) reads off the active
    provider.

    :cvar user_model: The provider's concrete :class:`BaseUser` subclass.
    :cvar token_payload_model: The provider's concrete :class:`BaseTokenPayload`
        subclass.
    :cvar supports_ambient_session: Whether the provider can sign a caller in
        from an ambient session cookie already carried on the request. Defaults
        to ``False``; a provider that validates such a cookie overrides it.
    """

    user_model: ClassVar[type[BaseUser]]
    token_payload_model: ClassVar[type[BaseTokenPayload]]
    supports_ambient_session: ClassVar[bool] = False

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[None, None]:
        """Yield control while the provider's resources are active.

        Default to a no-op for providers whose SDK needs no async setup or
        teardown; a provider whose SDK is itself an async context manager
        overrides this to enter it.

        :yield: ``None`` once the provider's resources are ready.
        """
        yield
