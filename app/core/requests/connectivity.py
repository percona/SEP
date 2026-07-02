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

"""Define the normalized connectivity-probe result model and outcome classifier.

Shared by the overridable ``RemoteAPI.check_connectivity()`` probe and the SEP
settings connectivity-check endpoint so both speak a single, stable shape.
"""

import ssl
from enum import StrEnum

from aiohttp import ClientSSLError
from fastapi import HTTPException, status
from pydantic import BaseModel

#: Per-probe upper bound. A hung endpoint must not stall the whole fan-out, so
#: each probe is wrapped in this timeout independent of the client's own pool
#: timeouts.
PROBE_TIMEOUT_SECONDS = 5

#: HTTP statuses that mean "the server answered, but rejected our credentials".
_AUTH_FAILURE_STATUSES = frozenset(
    {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}
)


class ConnectivityStatusEnum(StrEnum):
    """Enumerate the mutually-exclusive outcomes of a connectivity probe."""

    REACHABLE = "reachable"
    AUTH_FAILED = "auth_failed"
    ERROR = "error"
    UNREACHABLE = "unreachable"
    SSL_ERROR = "ssl_error"
    TIMEOUT = "timeout"


#: Human-readable default ``detail`` per outcome. Deliberately fixed strings so
#: the probe never echoes the configured API key or any credential embedded in
#: an endpoint URL.
_DEFAULT_DETAILS: dict[ConnectivityStatusEnum, str] = {
    ConnectivityStatusEnum.REACHABLE: "Reachable.",
    ConnectivityStatusEnum.AUTH_FAILED: "Authentication failed.",
    ConnectivityStatusEnum.ERROR: "Endpoint returned an error response.",
    ConnectivityStatusEnum.UNREACHABLE: "Connection failed.",
    ConnectivityStatusEnum.SSL_ERROR: "SSL verification failed.",
    ConnectivityStatusEnum.TIMEOUT: "Connection timed out.",
}


class ConnectivityResult(BaseModel):
    """Represent the outcome of probing a single external / inter-service endpoint.

    :param service: Stable identifier of the probed service (e.g. ``"pmm"``).
    :type service: str
    :param reachable: ``True`` only when the endpoint answered successfully.
    :type reachable: bool
    :param status: Machine-readable outcome state.
    :type status: ConnectivityStatusEnum
    :param detail: Human-readable status / error, free of secrets.
    :type detail: str
    :param version: Optional remote version string when the probe exposes one.
    :type version: str | None
    """

    service: str
    reachable: bool
    status: ConnectivityStatusEnum
    detail: str
    version: str | None = None


def classify_connectivity_error(exc: BaseException) -> ConnectivityStatusEnum:
    """Map a probe exception to its :class:`ConnectivityStatusEnum` outcome.

    Order matters: :class:`TimeoutError` and the aiohttp SSL errors are both
    :class:`OSError` subclasses, so they are checked before falling through to
    the generic unreachable outcome.

    :param exc: The exception raised while probing the endpoint.
    :type exc: BaseException
    :return: The classified outcome state.
    :rtype: ConnectivityStatusEnum
    """
    if isinstance(exc, TimeoutError):
        return ConnectivityStatusEnum.TIMEOUT
    if isinstance(exc, HTTPException):
        if exc.status_code in _AUTH_FAILURE_STATUSES:
            return ConnectivityStatusEnum.AUTH_FAILED
        # The server answered, but with an HTTP error (wrong base path, 4xx/5xx).
        # That is not a healthy endpoint, so it is distinct from REACHABLE.
        return ConnectivityStatusEnum.ERROR
    if isinstance(exc, ClientSSLError | ssl.SSLError):
        return ConnectivityStatusEnum.SSL_ERROR
    return ConnectivityStatusEnum.UNREACHABLE


def build_connectivity_result(
    service: str,
    probe_status: ConnectivityStatusEnum,
    *,
    version: str | None = None,
    detail: str | None = None,
) -> ConnectivityResult:
    """Build a :class:`ConnectivityResult` with a safe default ``detail``.

    :param service: Stable identifier of the probed service.
    :type service: str
    :param probe_status: The classified outcome state.
    :type probe_status: ConnectivityStatusEnum
    :param version: Optional remote version string.
    :type version: str | None
    :param detail: Override for the default per-status detail string.
    :type detail: str | None
    :return: The normalized connectivity result.
    :rtype: ConnectivityResult
    """
    return ConnectivityResult(
        service=service,
        reachable=probe_status is ConnectivityStatusEnum.REACHABLE,
        status=probe_status,
        detail=detail or _DEFAULT_DETAILS[probe_status],
        version=version,
    )
