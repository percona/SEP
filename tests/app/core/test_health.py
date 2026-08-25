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

"""Define tests for the shared ``/health`` router and its local readiness probe."""

import socket
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from http.client import HTTPException
from time import monotonic
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine, create_async_engine
from sqlmodel.pool import StaticPool
from starlette import status
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.health import (
    _resolve_probe_host,
    _resolve_probe_host_header,
    build_health_router,
    HEALTH_PATH,
    wait_for_api_ready,
)
from tests.app.conftest import HealthProbeServer

PROBE_LOGGER = "app.core.health"

# One recorded probe interaction: ``("request", method, path, headers)`` or ``("close",)``.
JournalEntry = tuple[Any, ...]


def _build_app(session_maker_factory: Callable[[], async_sessionmaker]) -> FastAPI:
    app = FastAPI()
    app.include_router(build_health_router(session_maker_factory))
    return app


async def _get_health(app: FastAPI) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    return response.status_code, response.json()


@pytest_asyncio.fixture(name="reachable_engine")
async def reachable_engine_fixture() -> AsyncIterator[AsyncEngine]:
    """Yield an in-memory SQLite engine for the reachable-database cases."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_health_ok_when_db_reachable(reachable_engine: AsyncEngine) -> None:
    """Test a successful ``SELECT 1`` yields 200 with an ``ok`` body."""
    app = _build_app(lambda: get_async_session_maker_from_engine(reachable_engine))

    status_code, body = await _get_health(app)

    assert status_code == status.HTTP_200_OK
    assert body == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_503_when_db_unreachable() -> None:
    """Return 503 when the database is unreachable.

    An engine at an unopenable path makes ``SELECT 1`` raise a real
    ``OperationalError``, which the route surfaces as 503 -- exercising the
    failure path with a genuine DB error rather than a mocked session.
    """
    engine = create_async_engine("sqlite+aiosqlite:////nonexistent/dir/health.db")
    try:
        app = _build_app(lambda: get_async_session_maker_from_engine(engine))

        status_code, body = await _get_health(app)

        assert status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert body == {"status": "unavailable"}
    finally:
        await engine.dispose()


def test_health_excluded_from_openapi() -> None:
    """Keep ``/health`` out of the generated OpenAPI document.

    It is registered with ``include_in_schema=False`` so it never enters the
    OpenAPI document the frontend codegen guard tracks.
    """
    app = _build_app(async_sessionmaker)

    assert "/health" not in app.openapi().get("paths", {})


def test_health_path_constant_matches_the_registered_route() -> None:
    """Pin ``HEALTH_PATH`` to the path the router actually registers.

    The readiness probe polls ``HEALTH_PATH`` against a live listener, so the
    constant and the route have to move together or the probe silently polls a
    404 for its whole deadline.
    """
    app = _build_app(async_sessionmaker)

    assert HEALTH_PATH == "/health"
    assert HEALTH_PATH in {route.path for route in app.routes}


class _FakeResponse:
    """Stand in for an ``http.client`` response carrying a fixed status."""

    def __init__(self, status_code: int) -> None:
        self.status = status_code

    def read(self) -> bytes:
        """Fail the test: draining the body is what an endless body exploits."""
        raise AssertionError("the probe must not read the response body")


class _FakeConnection:
    """Stand in for ``HTTPConnection``, replaying one queued outcome."""

    def __init__(
        self, outcome: int | BaseException, journal: list[JournalEntry]
    ) -> None:
        self._outcome = outcome
        self._journal = journal
        self.closed = 0

    def request(
        self, method: str, path: str, headers: dict[str, str] | None = None
    ) -> None:
        """Record the request and raise when the queued outcome is an exception."""
        self._journal.append(("request", method, path, dict(headers or {})))
        if isinstance(self._outcome, BaseException):
            raise self._outcome

    def getresponse(self) -> _FakeResponse:
        """Return the queued response."""
        assert not isinstance(self._outcome, BaseException)
        return _FakeResponse(self._outcome)

    def close(self) -> None:
        """Record that the caller closed the connection."""
        self.closed += 1
        self._journal.append(("close",))


class _ConnectionFactory:
    """Build :class:`_FakeConnection` objects from a queue of outcomes."""

    def __init__(self, outcomes: list[int | BaseException]) -> None:
        self._outcomes = list(outcomes)
        # Exhaustion repeats the last scripted outcome; defaulting to a 200 would
        # silently open the gate in the tests that exercise the deadline.
        self._last = self._outcomes[-1] if self._outcomes else status.HTTP_200_OK
        self.journal: list[JournalEntry] = []
        self.connections: list[_FakeConnection] = []
        self.constructor_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: object, **kwargs: object) -> _FakeConnection:
        """Return the next fake connection, recording constructor arguments."""
        self.constructor_calls.append((args, kwargs))
        outcome = self._outcomes.pop(0) if self._outcomes else self._last
        connection = _FakeConnection(outcome, self.journal)
        self.connections.append(connection)
        return connection

    @property
    def attempts(self) -> int:
        """Return how many connections were constructed."""
        return len(self.connections)

    @property
    def sent_headers(self) -> list[dict[str, str]]:
        """Return the headers of every request the probe issued."""
        return [entry[3] for entry in self.journal if entry[0] == "request"]


@pytest.fixture(name="no_sleep")
def no_sleep_fixture(mocker: MockerFixture) -> MagicMock:
    """Replace the probe's ``sleep`` with a recorder so polling loops run instantly."""
    return mocker.patch("app.core.health.sleep")


def _patch_connection(
    mocker: MockerFixture, outcomes: list[int | BaseException]
) -> _ConnectionFactory:
    """Install a fake ``HTTPConnection`` replaying ``outcomes`` in order."""
    factory = _ConnectionFactory(outcomes)
    mocker.patch("app.core.health.HTTPConnection", factory)
    return factory


def _build_host_checked_app(allowed_hosts: list[str]) -> FastAPI:
    """Return an app whose health path sits behind ``TrustedHostMiddleware``."""
    app = FastAPI()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.get(HEALTH_PATH)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


class TestResolveProbeHost:
    """Cover translating a listener's bind address into a connectable host."""

    @pytest.mark.parametrize(
        ("bind_host", "expected"),
        [
            ("0.0.0.0", "127.0.0.1"),
            ("::", "::1"),
            ("::0", "::1"),
            ("0:0:0:0:0:0:0:0", "::1"),
            ("127.0.0.1", "127.0.0.1"),
            ("::1", "::1"),
            ("10.1.2.3", "10.1.2.3"),
            ("localhost", "localhost"),
            ("sep.internal", "sep.internal"),
            ("0.0.0.0.0", "0.0.0.0.0"),
        ],
        ids=[
            "ipv4-unspecified",
            "ipv6-unspecified",
            "ipv6-unspecified-short",
            "ipv6-unspecified-expanded",
            "ipv4-loopback",
            "ipv6-loopback",
            "routable-ipv4",
            "hostname",
            "dotted-hostname",
            "not-an-address",
        ],
    )
    def test_unspecified_binds_resolve_to_loopback(
        self, bind_host: str, expected: str
    ) -> None:
        """Map the unspecified address to loopback and pass every other host through.

        Containers bind ``0.0.0.0``, which is bind-only; dialling it is not
        portable, so the probe aims at loopback instead. The equivalent IPv6
        spellings resolve the same way, and anything that is not an IP literal —
        including a string that merely looks like one — is dialled verbatim.
        """
        assert _resolve_probe_host(bind_host) == expected


class TestResolveProbeHostHeader:
    """Cover picking a ``Host`` header ``TrustedHostMiddleware`` will accept."""

    def test_empty_allowed_hosts_uses_the_connect_host(self) -> None:
        """Send the dialled host when no host restriction is configured."""
        assert _resolve_probe_host_header("127.0.0.1", []) == "127.0.0.1"

    def test_wildcard_allowed_hosts_uses_the_connect_host(self) -> None:
        """Send the dialled host when ``*`` admits every hostname."""
        assert _resolve_probe_host_header("127.0.0.1", ["*"]) == "127.0.0.1"

    def test_listed_connect_host_is_preferred(self) -> None:
        """Send the dialled host when the allow-list already names it."""
        allowed = ["sep.example.com", "127.0.0.1"]

        assert _resolve_probe_host_header("127.0.0.1", allowed) == "127.0.0.1"

    def test_disjoint_allow_list_borrows_an_allowed_hostname(self) -> None:
        """Use a configured hostname when the allow-list excludes loopback.

        A hardened deployment sets ``ALLOWED_HOSTS`` to its public names, so a
        ``Host: 127.0.0.1`` probe would be answered ``400`` for the whole
        deadline and the gate would never open.
        """
        allowed = ["sep.example.com", "sep-alt.example.com"]

        assert _resolve_probe_host_header("127.0.0.1", allowed) == "sep.example.com"

    def test_exact_pattern_wins_over_a_wildcard_pattern(self) -> None:
        """Prefer an exact hostname over a pattern that cannot be sent verbatim."""
        allowed = ["*.example.com", "sep.example.com"]

        assert _resolve_probe_host_header("127.0.0.1", allowed) == "sep.example.com"

    def test_wildcard_only_allow_list_synthesizes_a_matching_hostname(self) -> None:
        """Build a hostname from the wildcard when there is none to borrow.

        A wildcard-only allow-list is a supported configuration, so sending the
        dialled host instead would earn a ``400`` for the whole deadline and start
        beat ungated against a perfectly healthy API. Only the ``*.`` spelling is
        covered because ``TrustedHostMiddleware.__init__`` asserts it for every
        ``*``-prefixed entry, so no other wildcard shape reaches a running
        deployment.
        """
        assert _resolve_probe_host_header("127.0.0.1", ["*.example.com"]) == (
            "readiness.example.com"
        )

    def test_blank_entries_are_ignored(self) -> None:
        """Skip empty allow-list entries rather than sending an empty ``Host``."""
        assert _resolve_probe_host_header("127.0.0.1", ["", "sep.example.com"]) == (
            "sep.example.com"
        )

    @pytest.mark.parametrize(
        ("connect_host", "allowed_hosts", "expected_status"),
        [
            ("127.0.0.1", ["*"], status.HTTP_200_OK),
            ("127.0.0.1", ["127.0.0.1"], status.HTTP_200_OK),
            ("127.0.0.1", ["sep.example.com"], status.HTTP_200_OK),
            ("127.0.0.1", ["", "sep.example.com"], status.HTTP_200_OK),
            ("127.0.0.1", ["localhost", "sep.example.com"], status.HTTP_200_OK),
            ("127.0.0.1", ["*.example.com"], status.HTTP_200_OK),
            ("127.0.0.1", ["*.a.example.com", "*.b.example.com"], status.HTTP_200_OK),
            ("::1", ["::1"], status.HTTP_400_BAD_REQUEST),
        ],
        ids=[
            "wildcard",
            "loopback-listed",
            "single-public-name",
            "blank-entry-skipped",
            "first-of-several",
            "wildcard-only",
            "several-wildcards",
            "ipv6-literal-degrades",
        ],
    )
    def test_header_is_judged_by_the_real_middleware(
        self, connect_host: str, allowed_hosts: list[str], expected_status: int
    ) -> None:
        """Drive the resolved header through Starlette's own host check.

        Re-implementing the middleware's matching rule in the test would let the
        two drift; this asks the middleware itself. The IPv6 row is a recorded
        limit, not an aspiration: Starlette compares ``host.split(":")[0]``, which
        no IPv6 literal can satisfy, so that deployment leaves the gate to its
        deadline.
        """
        client = TestClient(_build_host_checked_app(allowed_hosts))
        header = _resolve_probe_host_header(connect_host, allowed_hosts)

        response = client.get(HEALTH_PATH, headers={"Host": header})

        assert response.status_code == expected_status


class TestWaitForApiReady:
    """Cover the readiness gate's polling, deadline and logging behaviour."""

    def test_returns_true_without_sleeping_when_already_serving(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Return immediately when the very first probe answers 200.

        A restart where the API is already up must not pay a poll interval, which
        is what keeps startup from regressing when the API comes up quickly.
        """
        factory = _patch_connection(mocker, [status.HTTP_200_OK])

        assert wait_for_api_ready("127.0.0.1", 8000) is True
        assert factory.attempts == 1
        no_sleep.assert_not_called()

    def test_polls_through_connection_refused_until_the_api_listens(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Keep polling while the socket refuses, then succeed once it answers."""
        outcomes: list[int | BaseException] = [
            ConnectionRefusedError(),
            ConnectionRefusedError(),
            status.HTTP_200_OK,
        ]
        factory = _patch_connection(mocker, outcomes)

        assert wait_for_api_ready("127.0.0.1", 8000, interval=0.01) is True
        assert factory.attempts == len(outcomes)
        assert no_sleep.call_count == len(outcomes) - 1

    @pytest.mark.parametrize(
        "not_ready_status",
        [
            status.HTTP_301_MOVED_PERMANENTLY,
            status.HTTP_302_FOUND,
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ],
    )
    def test_only_200_is_treated_as_ready(
        self, mocker: MockerFixture, no_sleep: MagicMock, not_ready_status: int
    ) -> None:
        """Keep polling on any non-200 and open the gate only on a 200.

        A 503 means the listener is up but its database is not, which is exactly
        the state a periodic task calling SEP's own API cannot use; a 400 means
        the host header was rejected; a 3xx means something other than the health
        route answered. None of them is readiness.
        """
        outcomes: list[int | BaseException] = [
            not_ready_status,
            not_ready_status,
            status.HTTP_200_OK,
        ]
        factory = _patch_connection(mocker, outcomes)

        assert wait_for_api_ready("127.0.0.1", 8000, interval=0.01) is True
        assert factory.attempts == len(outcomes)

    def test_returns_false_and_logs_the_last_outcome_on_timeout(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Stop at the deadline, naming the last observed outcome.

        The gate is best-effort: the caller starts beat anyway, so the log line is
        the only thing that makes a permanently unready API actionable. Real
        ``sleep`` runs here so the deadline is reached by waiting, not by spinning.
        """
        _patch_connection(mocker, [status.HTTP_503_SERVICE_UNAVAILABLE])

        with caplog.at_level("ERROR", logger=PROBE_LOGGER):
            ready = wait_for_api_ready("127.0.0.1", 8000, timeout=0.05, interval=0.01)

        assert ready is False
        errors = [record for record in caplog.records if record.levelname == "ERROR"]
        assert errors, "the timeout must be logged"
        assert "HTTP 503" in errors[-1].getMessage()

    def test_timeout_log_names_the_last_connection_error(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Name the transport failure when the socket never accepted at all."""
        _patch_connection(mocker, [ConnectionRefusedError("nope")])

        with caplog.at_level("ERROR", logger=PROBE_LOGGER):
            assert (
                wait_for_api_ready("127.0.0.1", 8000, timeout=0.05, interval=0.01)
                is False
            )

        errors = [record for record in caplog.records if record.levelname == "ERROR"]
        assert errors, "the timeout must be logged"
        assert "ConnectionRefusedError" in errors[-1].getMessage()

    def test_zero_timeout_still_probes_once(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Make one attempt even with no time budget, so a live API is not missed."""
        factory = _patch_connection(mocker, [status.HTTP_200_OK])

        assert wait_for_api_ready("127.0.0.1", 8000, timeout=0.0) is True
        assert factory.attempts == 1
        no_sleep.assert_not_called()

    def test_every_attempt_closes_its_connection(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Close the socket on success and on failure alike.

        The loop can run for the whole deadline, so a connection leaked per
        attempt would exhaust file descriptors before the gate ever opens.
        """
        outcomes: list[int | BaseException] = [
            ConnectionRefusedError(),
            status.HTTP_503_SERVICE_UNAVAILABLE,
            status.HTTP_200_OK,
        ]
        factory = _patch_connection(mocker, outcomes)

        wait_for_api_ready("127.0.0.1", 8000, interval=0.01)

        assert factory.attempts == len(outcomes)
        assert all(connection.closed == 1 for connection in factory.connections)

    def test_request_timeout_bounds_each_attempt(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Pass the per-attempt timeout to the connection.

        Without it a listener that accepts but never answers would block the gate
        past its own deadline.
        """
        request_timeout = 1.25
        factory = _patch_connection(mocker, [status.HTTP_200_OK])

        wait_for_api_ready("127.0.0.1", 8000, request_timeout=request_timeout)

        _, kwargs = factory.constructor_calls[0]
        assert kwargs["timeout"] == request_timeout

    def test_attempt_timeout_is_capped_by_the_remaining_budget(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Trim each attempt to the time left, so the total cannot overshoot.

        A generous ``request_timeout`` against a listener that accepts and never
        answers would otherwise let one attempt run past the whole deadline.
        """
        budget = 0.2
        factory = _patch_connection(mocker, [ConnectionRefusedError()])

        wait_for_api_ready(
            "127.0.0.1", 8000, timeout=budget, interval=0.01, request_timeout=30.0
        )

        assert factory.constructor_calls
        assert all(
            kwargs["timeout"] <= budget for _, kwargs in factory.constructor_calls
        )

    def test_probes_the_health_path_with_a_resolved_host_header(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Send ``GET /health`` with a host header the allow-list admits."""
        port = 8000
        factory = _patch_connection(mocker, [status.HTTP_200_OK])

        wait_for_api_ready(
            "0.0.0.0", port, allowed_hosts=["sep.example.com"], request_timeout=1.0
        )

        args, _ = factory.constructor_calls[0]
        assert args[0] == "127.0.0.1"
        assert args[1] == port
        method, path, headers = next(
            entry[1:] for entry in factory.journal if entry[0] == "request"
        )
        assert (method, path) == ("GET", HEALTH_PATH)
        assert headers["Host"] == "sep.example.com"

    def test_sends_no_headers_beyond_host_and_connection(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Keep the probe request free of credentials, cookies and auth headers.

        The probe reaches an unauthenticated route on a listener it does not own,
        so anything extra it sends is a leak with no upside.
        """
        factory = _patch_connection(mocker, [status.HTTP_200_OK])

        wait_for_api_ready("127.0.0.1", 8000)

        assert factory.sent_headers == [{"Host": "127.0.0.1", "Connection": "close"}]

    def test_protocol_errors_are_treated_as_not_ready(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Treat a malformed HTTP reply as not-ready instead of crashing.

        ``HTTPException`` is not an ``OSError``, so it needs its own guard or a
        half-open listener would take the gate down with a traceback.
        """
        outcomes: list[int | BaseException] = [
            HTTPException("bad status line"),
            status.HTTP_200_OK,
        ]
        factory = _patch_connection(mocker, outcomes)

        assert wait_for_api_ready("127.0.0.1", 8000, interval=0.01) is True
        assert factory.attempts == len(outcomes)

    def test_a_header_http_client_rejects_is_treated_as_not_ready(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Absorb the bare ``ValueError`` a CR/LF-bearing ``Host`` value raises.

        ``putheader`` refuses an embedded newline with a plain ``ValueError``,
        which is neither an ``OSError`` nor an ``HTTPException``. Letting it out
        would kill the beat child with a traceback instead of degrading to an
        ungated start, and the value comes from ``ALLOWED_HOSTS``.
        """
        _patch_connection(mocker, [ValueError("Invalid header value")])

        assert (
            wait_for_api_ready(
                "127.0.0.1",
                8000,
                allowed_hosts=["sep.example.com\r\nX-Evil: 1"],
                timeout=0.0,
            )
            is False
        )

    def test_the_wait_is_announced_above_the_default_log_level(
        self,
        mocker: MockerFixture,
        no_sleep: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Log the wait at ``WARNING`` so a default install sees it.

        ``LOGGING`` defaults to ``WARNING``, and this line is the only account of
        why beat has not started yet; at ``INFO`` an operator would watch beat
        idle for the whole deadline with no reason given.
        """
        _patch_connection(mocker, [status.HTTP_200_OK])

        with caplog.at_level("WARNING", logger=PROBE_LOGGER):
            assert wait_for_api_ready("127.0.0.1", 8000) is True

        warnings = [
            record for record in caplog.records if record.levelname == "WARNING"
        ]
        assert warnings, "the wait must be visible at the default log level"
        assert "Waiting up to" in warnings[0].getMessage()

    def test_keyboard_interrupt_is_not_swallowed(
        self, mocker: MockerFixture, no_sleep: MagicMock
    ) -> None:
        """Let ``Ctrl-C`` out of the loop so shutdown is not delayed.

        ``KeyboardInterrupt`` is a ``BaseException``, so a bare ``except`` would
        trap it and keep polling until the deadline.
        """
        _patch_connection(mocker, [KeyboardInterrupt()])

        with pytest.raises(KeyboardInterrupt):
            wait_for_api_ready("127.0.0.1", 8000)


@pytest.fixture(name="silent_listener_port")
def silent_listener_port_fixture() -> Iterator[int]:
    """Yield a port whose listener accepts connections and never answers.

    This is the shape uvicorn's socket takes between ``listen`` and the ASGI app
    serving requests, and the shape any unrelated service squatting the port
    takes. Nothing is ever accepted in userspace: the kernel backlog completes
    the handshake, so the probe connects and then waits for a reply forever.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(50)
    yield listener.getsockname()[1]
    listener.close()


class TestWaitForApiReadyAgainstARealSocket:
    """Cover the gate end to end over a real TCP listener."""

    def test_gate_stays_shut_until_the_api_listens_then_opens(
        self, health_probe_server: HealthProbeServer
    ) -> None:
        """Refuse to open while nothing listens, and open once the API answers.

        This is the ordering the fix turns on, over a real socket: the gate is
        shut for a port that refuses connections and opens for the same port once
        a server is serving 200 on it.
        """
        port = health_probe_server.port

        assert (
            wait_for_api_ready("127.0.0.1", port, timeout=0.2, interval=0.05) is False
        )

        health_probe_server.start()

        assert (
            wait_for_api_ready("127.0.0.1", port, timeout=10.0, interval=0.05) is True
        )

    def test_polls_a_real_503_until_the_database_is_reachable(
        self, health_probe_server: HealthProbeServer
    ) -> None:
        """Wait out a real 503 and open the gate when the probe flips to 200."""
        health_probe_server.statuses = [
            status.HTTP_503_SERVICE_UNAVAILABLE,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ]
        health_probe_server.start()

        ready = wait_for_api_ready(
            "127.0.0.1", health_probe_server.port, timeout=10.0, interval=0.05
        )

        assert ready is True
        assert not health_probe_server.statuses

    def test_opens_against_a_host_restricted_listener(
        self, health_probe_server: HealthProbeServer
    ) -> None:
        """Clear a listener that rejects an unlisted ``Host`` with 400.

        Proves the borrowed host header works against a real server, so the gate
        opens on a deployment whose ``ALLOWED_HOSTS`` excludes loopback.
        """
        health_probe_server.required_host = "sep.example.com"
        health_probe_server.start()

        ready = wait_for_api_ready(
            "0.0.0.0",
            health_probe_server.port,
            allowed_hosts=["sep.example.com"],
            timeout=10.0,
            interval=0.05,
        )

        assert ready is True
        _, headers = health_probe_server.requests[0]
        assert headers["Host"].split(":")[0] == "sep.example.com"

    def test_a_wrong_host_header_never_opens_the_gate(
        self, health_probe_server: HealthProbeServer
    ) -> None:
        """Treat the 400 a host rejection produces as not ready, timing out instead."""
        health_probe_server.required_host = "sep.example.com"
        health_probe_server.start()

        ready = wait_for_api_ready(
            "127.0.0.1",
            health_probe_server.port,
            allowed_hosts=["*"],
            timeout=0.3,
            interval=0.05,
        )

        assert ready is False
        assert health_probe_server.requests, "the listener should have been probed"

    def test_a_listener_that_never_answers_cannot_outlast_the_deadline(
        self, silent_listener_port: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Return within the budget against a listener that accepts and hangs.

        The connection succeeds, so the per-attempt timeout is the only thing
        that ends the attempt; without capping it to the remaining budget a
        generous ``request_timeout`` holds beat well past its own deadline.
        """
        budget = 0.3
        started_at = monotonic()

        with caplog.at_level("ERROR", logger=PROBE_LOGGER):
            ready = wait_for_api_ready(
                "127.0.0.1",
                silent_listener_port,
                timeout=budget,
                interval=0.05,
                request_timeout=30.0,
            )
        elapsed = monotonic() - started_at

        assert ready is False
        assert elapsed < budget + 1.0, f"gate overshot its budget by {elapsed:.2f}s"

    def test_a_redirect_is_reported_rather_than_followed(
        self, health_probe_server: HealthProbeServer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Report a 3xx as the outcome instead of chasing its ``Location``.

        The redirect points at a port nothing listens on, so a client that
        followed it would log a connection error instead of the 302, which is
        how this distinguishes reporting from following.
        """
        dead_port = 9
        health_probe_server.default_status = status.HTTP_302_FOUND
        health_probe_server.headers_to_send = {
            "Location": f"http://127.0.0.1:{dead_port}{HEALTH_PATH}"
        }
        health_probe_server.start()

        with caplog.at_level("ERROR", logger=PROBE_LOGGER):
            ready = wait_for_api_ready(
                "127.0.0.1", health_probe_server.port, timeout=0.2, interval=0.05
            )

        assert ready is False
        errors = [record for record in caplog.records if record.levelname == "ERROR"]
        assert errors, "the timeout must be logged"
        assert "HTTP 302" in errors[-1].getMessage()

    @pytest.mark.parametrize(
        "proxy_variable", ["http_proxy", "HTTP_PROXY", "ALL_PROXY", "all_proxy"]
    )
    def test_a_configured_proxy_does_not_divert_the_probe(
        self,
        health_probe_server: HealthProbeServer,
        monkeypatch: pytest.MonkeyPatch,
        proxy_variable: str,
    ) -> None:
        """Ignore a proxy set in the environment and dial the local listener.

        A container that exports a proxy for outbound traffic must not have its
        own readiness probe routed through it: the gate would never open, and
        the probe would announce the restart to whatever the proxy is.
        """
        monkeypatch.setenv(proxy_variable, "http://127.0.0.1:9")
        health_probe_server.start()

        ready = wait_for_api_ready(
            "127.0.0.1", health_probe_server.port, timeout=5.0, interval=0.05
        )

        assert ready is True
        assert health_probe_server.requests, "the local listener should have been hit"

    def test_a_long_interval_cannot_stretch_past_the_deadline(
        self, health_probe_server: HealthProbeServer
    ) -> None:
        """Clamp the wait to the deadline when the interval outlasts the budget.

        Measured on the real clock rather than a scripted one, so it holds however
        many times the implementation reads the clock.
        """
        budget = 0.2
        started_at = monotonic()

        ready = wait_for_api_ready(
            "127.0.0.1", health_probe_server.port, timeout=budget, interval=30.0
        )
        elapsed = monotonic() - started_at

        assert ready is False
        assert elapsed < budget + 1.0, f"gate slept past its deadline: {elapsed:.2f}s"


class TestHealthProbeServerFixture:
    """Guard the shared fixture's own contract, which several tests lean on."""

    def test_reserved_port_refuses_connections_before_start(
        self, health_probe_server: HealthProbeServer
    ) -> None:
        """Leave the reserved port closed until ``start`` is called.

        Every "not listening yet" test depends on this; if the constructor left
        the socket bound, those tests would pass for the wrong reason.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(2.0)
            with pytest.raises(ConnectionRefusedError):
                client.connect(("127.0.0.1", health_probe_server.port))

    def test_stop_releases_the_listener(
        self, health_probe_server: HealthProbeServer
    ) -> None:
        """Close the listener on ``stop`` so none outlives the test that made it.

        A leaked listener would make a later test's "nothing is listening" leg
        pass or fail depending on which port the OS handed out.
        """
        thread_count_before_serving = threading.active_count()
        health_probe_server.start()
        thread_count_while_serving = threading.active_count()
        assert thread_count_while_serving > thread_count_before_serving
        assert wait_for_api_ready(
            "127.0.0.1", health_probe_server.port, timeout=5.0, interval=0.05
        )

        health_probe_server.stop()

        assert threading.active_count() < thread_count_while_serving
        assert (
            wait_for_api_ready(
                "127.0.0.1", health_probe_server.port, timeout=0.2, interval=0.05
            )
            is False
        )
