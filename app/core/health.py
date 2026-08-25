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

"""Define the shared unauthenticated health endpoint and the local readiness gate.

The gate that polls the endpoint lives beside the route it dials so the two cannot
drift onto different paths.
"""

import logging
from collections.abc import Callable, Iterable
from http.client import HTTPConnection, HTTPException
from ipaddress import ip_address, IPv6Address
from time import monotonic, sleep
from typing import TYPE_CHECKING

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

HEALTH_PATH = "/health"

API_READINESS_TIMEOUT = 60.0
API_READINESS_POLL_INTERVAL = 0.5
API_READINESS_REQUEST_TIMEOUT = 2.0

_IPV4_LOOPBACK = "127.0.0.1"
_IPV6_LOOPBACK = "::1"

# Stands in for the ``*`` of a wildcard allow-list pattern. Any label satisfies
# Starlette's suffix comparison; a descriptive one makes the probe recognisable
# in an access log.
_WILDCARD_HOST_LABEL = "readiness"


def build_health_router(
    session_maker_factory: Callable[[], async_sessionmaker],
) -> APIRouter:
    """Build a router exposing an unauthenticated ``GET /health`` liveness probe.

    The probe confirms the server is accepting requests and its database is
    reachable via a ``SELECT 1`` round-trip. Schema currency is not re-checked
    here, so a reachable database behind a responding server implies migrations
    are applied only where they finish before the server starts — as under an
    entrypoint that runs ``alembic upgrade heads`` first. A deployment that
    starts migrations alongside the server, such as one process manager
    supervising both, owes its own completion signal.

    :param session_maker_factory: The service's ``get_async_session_maker``;
        called per request to obtain a session bound to that service's engine.
    :return: A router carrying the ``GET /health`` route.
    """
    router = APIRouter()

    @router.get(HEALTH_PATH, include_in_schema=False)
    async def health() -> JSONResponse:
        """Return ``200`` when the database is reachable, ``503`` otherwise."""
        try:
            async with session_maker_factory()() as session:
                session: AsyncSession
                (await session.exec(select(1))).one()
        except SQLAlchemyError:
            return JSONResponse(
                {"status": "unavailable"},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return JSONResponse({"status": "ok"})

    return router


def _resolve_probe_host(bind_host: str) -> str:
    """Return a host a same-machine probe can dial for a listener on ``bind_host``.

    The unspecified address is bind-only: a listener on it accepts on loopback,
    which is the only address a same-host probe can portably dial. Asking
    ``ipaddress`` rather than matching literals covers every spelling of it, so a
    container configured with ``::0`` is treated like one configured with ``::``.

    :param bind_host: The address the server binds, as configured for Uvicorn.
    :return: ``bind_host`` itself, or the matching loopback address when it names
        the unspecified address.
    """
    try:
        address = ip_address(bind_host)
    except ValueError:
        return bind_host
    if not address.is_unspecified:
        return bind_host
    return _IPV6_LOOPBACK if isinstance(address, IPv6Address) else _IPV4_LOOPBACK


def _resolve_probe_host_header(connect_host: str, allowed_hosts: Iterable[str]) -> str:
    """Return a ``Host`` header value ``TrustedHostMiddleware`` will admit.

    A deployment that restricts ``ALLOWED_HOSTS`` to its public names answers a
    ``Host: 127.0.0.1`` request with ``400`` before any route runs, so a probe
    that dials loopback borrows a configured hostname instead. Starlette compares
    only the hostname portion of the header, so the port is irrelevant. A pattern
    is preferred verbatim when it is a concrete hostname; a wildcard is turned
    into one that satisfies the same suffix comparison the middleware applies.

    :param connect_host: The host the probe dials.
    :param allowed_hosts: The configured ``TrustedHostMiddleware`` patterns; an
        empty iterable means the middleware is not installed.
    :return: The hostname to send as ``Host``.
    """
    patterns = [pattern for pattern in allowed_hosts if pattern]
    if not patterns or "*" in patterns or connect_host in patterns:
        return connect_host
    hostnames = [pattern for pattern in patterns if not pattern.startswith("*")]
    if hostnames:
        return hostnames[0]
    return f"{_WILDCARD_HOST_LABEL}{patterns[0][1:]}"


def _probe_health_once(
    connect_host: str, port: int, host_header: str, attempt_timeout: float
) -> tuple[int | None, str]:
    """Issue one ``GET`` against the health path and report what came back.

    Uses ``http.client`` rather than a higher-level client so the probe cannot be
    diverted by ``http_proxy`` in the environment or follow a redirect away from
    the local listener, and so no request-level retry hides the poll count. The
    body is never read: only the status matters, and draining a response refreshes
    the socket timeout per chunk, so a listener dribbling an endless body would
    hold the caller well past its deadline.

    :param connect_host: The host to dial.
    :param port: The port to dial.
    :param host_header: The ``Host`` header to send.
    :param attempt_timeout: Seconds to allow for connect plus response headers.
    :return: The response status (``None`` when nothing answered) and a short
        description of the outcome for logging. A ``Host`` value carrying an
        embedded CR/LF is reported the same way: ``http.client`` rejects it with
        a bare ``ValueError``, which must not escape into the caller's process.
    """
    connection = HTTPConnection(connect_host, port, timeout=attempt_timeout)
    try:
        connection.request(
            "GET", HEALTH_PATH, headers={"Host": host_header, "Connection": "close"}
        )
        response = connection.getresponse()
    except (OSError, HTTPException, ValueError) as error:
        return None, f"{type(error).__name__}: {error}"
    else:
        return response.status, f"HTTP {response.status}"
    finally:
        connection.close()


def wait_for_api_ready(
    host: str,
    port: int,
    *,
    allowed_hosts: Iterable[str] = (),
    timeout: float = API_READINESS_TIMEOUT,
    interval: float = API_READINESS_POLL_INTERVAL,
    request_timeout: float = API_READINESS_REQUEST_TIMEOUT,
) -> bool:
    """Poll the local health path until it answers ``200`` or the deadline passes.

    Only ``200`` opens the gate. A ``503`` means the listener is up but its
    database is not, which is not a state a caller of SEP's own API can use, and
    a ``400`` means the host header was rejected — neither is readiness. The
    first attempt happens immediately, so an API that is already serving costs
    nothing.

    Every attempt after the first is bounded by whatever is left of ``timeout``,
    so total wall time stays inside the caller's budget against a listener that
    accepts a connection and then sends nothing — the shape uvicorn's socket
    takes while the ASGI app is still starting up. Two cases fall outside that
    bound: a listener that trickles its status line, since ``http.client``
    re-arms the socket timeout per ``recv``, and a caller passing a non-positive
    ``timeout``, whose single attempt runs on the full ``request_timeout``.

    The scheme is plain HTTP because the listener this gate fronts
    (``app.main``'s ``uvicorn.run``) is started without ``ssl_keyfile`` /
    ``ssl_certfile``; a TLS listener would need this probe changed in step.

    :param host: The address the API binds, as configured for Uvicorn.
    :param port: The port the API binds.
    :param allowed_hosts: The API's ``TrustedHostMiddleware`` patterns, used to
        pick a ``Host`` header the middleware admits.
    :param timeout: Total seconds to wait before giving up.
    :param interval: Seconds between attempts.
    :param request_timeout: Seconds to allow each individual attempt, itself
        capped by the time left in the overall budget.
    :return: ``True`` once the health path answered ``200``, ``False`` if the
        deadline passed first.
    """
    connect_host = _resolve_probe_host(host)
    host_header = _resolve_probe_host_header(connect_host, allowed_hosts)
    started_at = monotonic()
    deadline = started_at + timeout
    logger.warning(
        "Waiting up to %.1fs for the HTTP API at %s:%s to answer %s",
        timeout,
        connect_host,
        port,
        HEALTH_PATH,
    )
    outcome = "no attempt was made"
    first_attempt = True
    while True:
        remaining = deadline - monotonic()
        if not first_attempt and remaining <= 0:
            break
        # Only the first attempt can reach the uncapped branch, so a caller with
        # no budget at all still learns whether the API is already serving.
        attempt_timeout = (
            min(request_timeout, remaining) if remaining > 0 else request_timeout
        )
        first_attempt = False
        status_code, outcome = _probe_health_once(
            connect_host, port, host_header, attempt_timeout
        )
        if status_code == status.HTTP_200_OK:
            logger.info(
                "HTTP API at %s:%s is ready after %.1fs",
                connect_host,
                port,
                monotonic() - started_at,
            )
            return True
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(interval, remaining))

    logger.error(
        "HTTP API at %s:%s did not answer %s with 200 within %.1fs; last outcome: %s",
        connect_host,
        port,
        HEALTH_PATH,
        timeout,
        outcome,
    )
    return False
