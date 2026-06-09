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

"""Define a registry for RemoteAPI clients."""

__all__ = ["ClientRegistry"]

import asyncio
import logging
from collections import defaultdict
from collections.abc import Hashable
from typing import Any, ClassVar, TypeVar

from app.core.requests.remote_api import BaseRemoteAPI, RemoteAPI

T = TypeVar("T", bound=BaseRemoteAPI)
logger = logging.getLogger(__name__)


class ClientRegistry:
    """A registry for managing RemoteAPI clients.

    This class maintains a cache of RemoteAPI clients, ensuring that only one instance
    of each client configuration is created. It uses immutable keys to identify unique
    client configurations and provides thread-safe access to the clients.

    :cvar: IMMUTABLE_KEYS: A tuple of keys that are considered immutable for client
        configurations.
    :vartype IMMUTABLE_KEYS: ClassVar[tuple[str, ...]]
    """

    IMMUTABLE_KEYS: ClassVar[tuple[str, ...]] = (
        "endpoint",
        "verify_ssl",
        "ssl_cafile",
        "ssl_keyfile",
        "ssl_certfile",
    )

    def __init__(self) -> None:
        self._clients: dict[tuple[Hashable, ...], BaseRemoteAPI] = {}
        self._locks: defaultdict[tuple[Hashable, ...], asyncio.Lock] = defaultdict(
            asyncio.Lock
        )
        self._close_lock: asyncio.Lock = asyncio.Lock()
        self._closed: bool = False

    @property
    def closed(self) -> bool:
        """Indicate whether the registry is closed.

        :return: True if the registry is closed, False otherwise.
        :rtype: bool
        """
        return self._closed

    def _make_key(self, cls: type[T], **kwargs: Hashable) -> tuple[Hashable, ...]:
        """Create a unique key for the client based on class and immutable kwargs.

        :param cls: The class of the RemoteAPI client.
        :type cls: type[T]
        :param kwargs: The keyword arguments used to configure the client.
        :type kwargs: Hashable
        :return: A tuple representing the unique key for the client.
        :rtype: tuple[Hashable, ...]
        """
        key = [
            cls,
            *(
                kwargs.get(immutable_key)
                for immutable_key in self.IMMUTABLE_KEYS
                if immutable_key in kwargs
            ),
        ]
        return tuple(key)

    async def get(self, cls: type[T] = RemoteAPI, **kwargs: Any) -> T:
        """Get or create a RemoteAPI client instance.

        :param cls: The class of the RemoteAPI client. Defaults to :class:`RemoteAPI`.
        :type cls: type[T]
        :param kwargs: The keyword arguments used to configure the client.
        :type kwargs: Any
        :return: An instance of the RemoteAPI client.
        :rtype: T
        :raises RuntimeError: If the registry is closed.
        """
        if self.closed:
            raise ValueError("ClientRegistry is closed")

        key = self._make_key(cls, **kwargs)

        client = self._clients.get(key)
        if client is not None:
            return client

        async with self._locks[key]:
            client = self._clients.get(key)
            if client is not None:
                return client

            client = cls(**kwargs)
            self._clients[key] = await client.open()
            return client

    async def invalidate(self, endpoint: str) -> None:
        """Close and evict every cached client served from ``endpoint``.

        Removes the matching clients from the cache before closing them, so a
        subsequent :meth:`get` for the same configuration reconstructs a fresh
        client. Used to rebind PMM and other endpoint-keyed clients when their
        DB-backed settings override changes at runtime. A no-op when the
        registry is closed or when no cached client serves ``endpoint``.

        :param endpoint: The endpoint URL whose cached clients to evict.
            Compared trailing-slash-insensitively against each client's
            ``endpoint``.
        :type endpoint: str
        """
        normalized = endpoint.rstrip("/")
        async with self._close_lock:
            if self.closed:
                return
            matching = [
                (key, client)
                for key, client in self._clients.items()
                if str(client.endpoint).rstrip("/") == normalized
            ]
            for key, _client in matching:
                del self._clients[key]
                self._locks.pop(key, None)

        if not matching:
            return
        results = await asyncio.gather(
            *(client.close() for _key, client in matching), return_exceptions=True
        )
        for (_key, client), result in zip(matching, results, strict=False):
            if isinstance(result, Exception):
                logger.warning("Error closing client %r: %s", client.base_url, result)

    async def close_all(self) -> None:
        """Close all RemoteAPI clients and clear the registry.

        This method closes all clients in the registry and clears the internal cache.
        It is safe to call this method multiple times; subsequent calls will have no
        effect if the registry is already closed.
        """
        async with self._close_lock:
            if self.closed:
                return
            self._closed = True
            clients = list(self._clients.values())

        try:
            results = await asyncio.gather(
                *(client.close() for client in clients), return_exceptions=True
            )
            for client, result in zip(clients, results, strict=False):
                if isinstance(result, Exception):
                    logger.warning(
                        "Error closing client %r: %s", client.base_url, result
                    )
        finally:
            self._clients.clear()
            self._locks.clear()
