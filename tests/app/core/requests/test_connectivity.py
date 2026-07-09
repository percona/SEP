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

"""Define tests for the RemoteAPI connectivity-probe capability."""

import ssl

import pytest
from aioresponses import aioresponses
from fastapi import HTTPException, status

from app.core.requests import RemoteAPI
from app.core.requests.connectivity import (
    classify_connectivity_error,
    ConnectivityStatusEnum,
)
from app.core.requests.remote_api import BaseRemoteAPI
from app.sep.clients.pmm import PMMRemoteAPI


@pytest.fixture
def base_url() -> str:
    """Return the base URL for the probed API."""
    return "http://localhost:8000/"


@pytest.fixture
def remote_api(base_url: str) -> RemoteAPI:
    """Return a RemoteAPI instance with a non-secret API key."""
    return RemoteAPI(endpoint=base_url, error_detail_key="detail")


@pytest.fixture(autouse=True)
def clear_ssl_context_cache() -> None:
    """Reset the SSL-context lru_cache between tests."""
    BaseRemoteAPI.create_ssl_context.cache_clear()
    yield
    BaseRemoteAPI.create_ssl_context.cache_clear()


class TestClassifyConnectivityError:
    """Exercise the pure exception-to-outcome classifier."""

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (TimeoutError(), ConnectivityStatusEnum.TIMEOUT),
            (
                HTTPException(status.HTTP_401_UNAUTHORIZED),
                ConnectivityStatusEnum.AUTH_FAILED,
            ),
            (
                HTTPException(status.HTTP_403_FORBIDDEN),
                ConnectivityStatusEnum.AUTH_FAILED,
            ),
            (
                HTTPException(status.HTTP_502_BAD_GATEWAY),
                ConnectivityStatusEnum.ERROR,
            ),
            (
                HTTPException(status.HTTP_404_NOT_FOUND),
                ConnectivityStatusEnum.ERROR,
            ),
            (ssl.SSLError(), ConnectivityStatusEnum.SSL_ERROR),
            (ConnectionRefusedError(), ConnectivityStatusEnum.UNREACHABLE),
            (OSError(), ConnectivityStatusEnum.UNREACHABLE),
            (RuntimeError(), ConnectivityStatusEnum.UNREACHABLE),
        ],
    )
    def test_classifies_each_outcome(
        self, exc: BaseException, expected: ConnectivityStatusEnum
    ) -> None:
        """Map each exception to its expected outcome state."""
        assert classify_connectivity_error(exc) is expected

    def test_ssl_error_precedes_unreachable(self) -> None:
        """Classify an SSL error as ssl_error even though it is an OSError."""
        # ClientConnectorSSLError is an OSError subclass; the SSL arm must win.
        assert classify_connectivity_error(ssl.SSLError()) is (
            ConnectivityStatusEnum.SSL_ERROR
        )

    def test_timeout_precedes_unreachable(self) -> None:
        """Classify a TimeoutError as timeout even though it is an OSError."""
        assert issubclass(TimeoutError, OSError)
        assert classify_connectivity_error(TimeoutError()) is (
            ConnectivityStatusEnum.TIMEOUT
        )


class TestRemoteAPIDefaults:
    """Verify the probe capability is purely additive."""

    def test_default_probe_path_is_root(self, remote_api: RemoteAPI) -> None:
        """Default the probe route to the root path."""
        assert remote_api.connectivity_check_path == "/"

    def test_probe_path_not_a_model_field(self, remote_api: RemoteAPI) -> None:
        """Keep the probe path a ClassVar, out of the model field set."""
        assert "connectivity_check_path" not in type(remote_api).model_fields


class TestCheckConnectivity:
    """Exercise RemoteAPI.check_connectivity end-to-end against mocked HTTP."""

    @pytest.mark.asyncio
    async def test_reachable(self, remote_api: RemoteAPI, base_url: str) -> None:
        """Report reachable on a 2xx response."""
        with aioresponses() as mocked:
            mocked.get(base_url, status=status.HTTP_200_OK, payload={})
            async with remote_api:
                result = await remote_api.check_connectivity("svc")
        assert result.service == "svc"
        assert result.reachable is True
        assert result.status is ConnectivityStatusEnum.REACHABLE
        assert result.version is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "http_status",
        [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
    )
    async def test_auth_failure(
        self, remote_api: RemoteAPI, base_url: str, http_status: int
    ) -> None:
        """Report auth_failed and not-reachable on 401/403."""
        with aioresponses() as mocked:
            mocked.get(base_url, status=http_status, payload={"detail": "nope"})
            async with remote_api:
                result = await remote_api.check_connectivity("svc")
        assert result.reachable is False
        assert result.status is ConnectivityStatusEnum.AUTH_FAILED

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "http_status",
        [status.HTTP_404_NOT_FOUND, status.HTTP_500_INTERNAL_SERVER_ERROR],
    )
    async def test_error_on_non_auth_http_failure(
        self, remote_api: RemoteAPI, base_url: str, http_status: int
    ) -> None:
        """Report error (answered but unhealthy), not reachable, on 4xx/5xx."""
        with aioresponses() as mocked:
            mocked.get(base_url, status=http_status, payload={"detail": "nope"})
            async with remote_api:
                result = await remote_api.check_connectivity("svc")
        assert result.reachable is False
        assert result.status is ConnectivityStatusEnum.ERROR

    @pytest.mark.asyncio
    async def test_unreachable(self, remote_api: RemoteAPI, base_url: str) -> None:
        """Report unreachable on a connection error."""
        with aioresponses() as mocked:
            mocked.get(base_url, exception=ConnectionRefusedError("refused"))
            async with remote_api:
                result = await remote_api.check_connectivity("svc")
        assert result.reachable is False
        assert result.status is ConnectivityStatusEnum.UNREACHABLE

    @pytest.mark.asyncio
    async def test_ssl_error(self, remote_api: RemoteAPI, base_url: str) -> None:
        """Report ssl_error on an SSL failure, distinct from unreachable."""
        with aioresponses() as mocked:
            mocked.get(base_url, exception=ssl.SSLError("bad cert"))
            async with remote_api:
                result = await remote_api.check_connectivity("svc")
        assert result.reachable is False
        assert result.status is ConnectivityStatusEnum.SSL_ERROR

    @pytest.mark.asyncio
    async def test_timeout(self, remote_api: RemoteAPI, base_url: str) -> None:
        """Report timeout when the probe times out."""
        with aioresponses() as mocked:
            mocked.get(base_url, exception=TimeoutError())
            async with remote_api:
                result = await remote_api.check_connectivity("svc")
        assert result.reachable is False
        assert result.status is ConnectivityStatusEnum.TIMEOUT

    @pytest.mark.asyncio
    async def test_custom_probe_path(
        self, remote_api: RemoteAPI, base_url: str
    ) -> None:
        """Honor an explicit probe path override."""
        with aioresponses() as mocked:
            mocked.get(f"{base_url}health", status=status.HTTP_200_OK, payload={})
            async with remote_api:
                result = await remote_api.check_connectivity("svc", path="health")
        assert result.reachable is True

    @pytest.mark.asyncio
    async def test_never_leaks_api_key(self, base_url: str) -> None:
        """Keep the configured API key out of the result and its detail."""
        secret = "super-secret-key"
        api = RemoteAPI(endpoint=base_url)
        with aioresponses() as mocked:
            mocked.get(base_url, status=status.HTTP_401_UNAUTHORIZED, payload={})
            async with api:
                with api.auth(secret):
                    result = await api.check_connectivity("svc")
        assert secret not in result.detail
        assert secret not in result.model_dump_json()


class TestPMMCheckConnectivity:
    """Exercise the PMM-specific probe override."""

    @pytest.fixture
    def pmm_api(self, base_url: str) -> PMMRemoteAPI:
        """Return a PMMRemoteAPI instance with a dummy API key."""
        return PMMRemoteAPI(endpoint=base_url, api_key="pmm-secret")

    @pytest.mark.asyncio
    async def test_reachable_reports_version(
        self, pmm_api: PMMRemoteAPI, base_url: str
    ) -> None:
        """Hit /v1/version and report the version on success."""
        with aioresponses() as mocked:
            mocked.get(
                f"{base_url}v1/version",
                status=status.HTTP_200_OK,
                payload={"version": "3.1.0"},
            )
            async with pmm_api:
                result = await pmm_api.check_connectivity("pmm")
        assert result.reachable is True
        assert result.status is ConnectivityStatusEnum.REACHABLE
        assert result.version == "3.1.0"

    @pytest.mark.asyncio
    async def test_reachable_without_version_key(
        self, pmm_api: PMMRemoteAPI, base_url: str
    ) -> None:
        """Stay reachable when the version key is missing from the body."""
        with aioresponses() as mocked:
            mocked.get(
                f"{base_url}v1/version",
                status=status.HTTP_200_OK,
                payload={"unexpected": "shape"},
            )
            async with pmm_api:
                result = await pmm_api.check_connectivity("pmm")
        assert result.reachable is True
        assert result.version is None

    @pytest.mark.asyncio
    async def test_unreachable(self, pmm_api: PMMRemoteAPI, base_url: str) -> None:
        """Report unreachable when PMM cannot be reached."""
        with aioresponses() as mocked:
            mocked.get(
                f"{base_url}v1/version", exception=ConnectionRefusedError("refused")
            )
            async with pmm_api:
                result = await pmm_api.check_connectivity("pmm")
        assert result.reachable is False
        assert result.status is ConnectivityStatusEnum.UNREACHABLE

    @pytest.mark.asyncio
    async def test_error_on_non_auth_http_failure(
        self, pmm_api: PMMRemoteAPI, base_url: str
    ) -> None:
        """Report error (not reachable) when /v1/version returns a 5xx."""
        with aioresponses() as mocked:
            mocked.get(
                f"{base_url}v1/version",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                payload={},
            )
            async with pmm_api:
                result = await pmm_api.check_connectivity("pmm")
        assert result.reachable is False
        assert result.status is ConnectivityStatusEnum.ERROR

    @pytest.mark.asyncio
    async def test_never_leaks_api_key(
        self, pmm_api: PMMRemoteAPI, base_url: str
    ) -> None:
        """Keep the PMM API key out of the result."""
        with aioresponses() as mocked:
            mocked.get(
                f"{base_url}v1/version", status=status.HTTP_403_FORBIDDEN, payload={}
            )
            async with pmm_api:
                result = await pmm_api.check_connectivity("pmm")
        assert "pmm-secret" not in result.model_dump_json()
