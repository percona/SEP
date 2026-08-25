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
"""Cover the side-car's readiness gate in front of Celery beat."""

import logging
from configparser import RawConfigParser
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.inventory.config import inventory_settings
from app.sep.config import sep_settings
from app.tasks.config import tasks_settings
from sidecar import wait_for_api as helper
from tests.sidecar.conftest import SIDECAR_DIR

SUPERVISORD_CONF = SIDECAR_DIR / "supervisord.conf"
CONTAINERFILE = SIDECAR_DIR / "Containerfile.sidecar"

HELPER_INVOCATION = "python3 wait_for_api.py"
BEAT_INVOCATION = "celery -A app.celery beat"


@dataclass
class StubService:
    """Stand in for one service's settings, carrying only what the gate reads."""

    UVICORN_HOST: str = "0.0.0.0"
    UVICORN_PORT: int = 9000
    ALLOWED_HOSTS: list[str] = field(default_factory=lambda: ["*"])
    SSL_CERTFILE: str | None = None
    SSL_KEYFILE: str | None = None


@dataclass
class Probe:
    """Record one ``wait_for_api_ready`` call."""

    host: str
    port: int
    allowed_hosts: list[str]
    timeout: float


@pytest.fixture
def program_settings() -> dict[str, dict[str, str]]:
    """Return the side-car's supervisord programs, keyed by program name.

    ``RawConfigParser`` rather than the interpolating default: the file carries
    ``%(ENV_...)s`` names supervisord expands, which the default parser rejects.

    :return: Each ``[program:...]`` section's settings, keyed by the bare name.
    """
    parser = RawConfigParser()
    parser.read_string(SUPERVISORD_CONF.read_text(encoding="utf-8"))
    return {
        section.split(":", 1)[1]: dict(parser[section])
        for section in parser.sections()
        if section.startswith("program:")
    }


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Drive the gate over stub services against a clock the probes advance.

    ``monotonic`` is replaced rather than slept through so the shared-budget
    arithmetic is asserted exactly instead of approximately.

    :param monkeypatch: The attribute patcher.
    :return: A callable taking the stub services, the seconds each probe should
        consume and each probe's verdict, and returning the gate's own verdict
        alongside the calls it made.
    """
    clock = {"now": 0.0}
    monkeypatch.setattr(helper, "monotonic", lambda: clock["now"])

    def run(
        services: tuple[tuple[str, StubService], ...],
        elapsed: float = 0.0,
        verdicts: tuple[bool, ...] = (),
    ) -> tuple[bool, list[Probe]]:
        probes: list[Probe] = []
        answers = iter(verdicts)

        def fake_wait(
            host: str,
            port: int,
            *,
            allowed_hosts: list[str],
            timeout: float,
            interval: float,
        ) -> bool:
            probes.append(Probe(host, port, list(allowed_hosts), timeout))
            clock["now"] += elapsed
            return next(answers, True)

        monkeypatch.setattr(helper, "wait_for_api_ready", fake_wait)
        monkeypatch.setattr(helper, "GATED_SERVICES", services)
        return helper.wait_for_apis(), probes

    return run


def test_beat_runs_the_gate_before_beat(program_settings):
    """Assert the gate precedes the beat command in the same program."""
    command = program_settings["celery-beat"]["command"]

    assert HELPER_INVOCATION in command
    assert BEAT_INVOCATION in command
    assert command.index(HELPER_INVOCATION) < command.index(BEAT_INVOCATION)


def test_beat_starts_whatever_the_gate_reports(program_settings):
    """Reject an `&&` between the two, which would make a degraded gate fatal.

    The gate exits 0 by design, but chaining on success would turn any future
    non-zero exit — an ImportError, a settings failure — into a container that
    schedules nothing at all, the outcome the gate exists to avoid.
    """
    command = program_settings["celery-beat"]["command"]
    between = command[
        command.index(HELPER_INVOCATION) + len(HELPER_INVOCATION) : command.index(
            BEAT_INVOCATION
        )
    ]

    assert "&&" not in between
    assert ";" in between


def test_beat_execs_and_stops_as_a_group(program_settings):
    """Assert the stop path reaches both the wait and the beat it becomes."""
    beat = program_settings["celery-beat"]

    assert f"exec {BEAT_INVOCATION}" in beat["command"]
    assert beat["stopasgroup"] == "true"
    assert beat["killasgroup"] == "true"


def test_the_worker_is_not_gated(program_settings):
    """Leave the worker starting immediately — it idles until a task arrives."""
    assert HELPER_INVOCATION not in program_settings["celery-worker"]["command"]


def test_the_helper_reaches_the_image():
    """Assert the helper is copied in; bundle.tgz carries no sidecar/ file."""
    assert "./sidecar/wait_for_api.py ./wait_for_api.py" in CONTAINERFILE.read_text(
        encoding="utf-8"
    )


def test_every_supervised_api_is_gated():
    """Assert the gate covers the three services supervisord starts.

    The two a periodic task dials are ``INVENTORY_ENDPOINT`` and ``TASKS_ENDPOINT``;
    ``sep`` is included because its lifespan is what seeds the beat schedule.
    """
    assert [name for name, _ in helper.GATED_SERVICES] == ["sep", "inventory", "tasks"]
    assert [service for _, service in helper.GATED_SERVICES] == [
        sep_settings,
        inventory_settings,
        tasks_settings,
    ]


def test_each_service_is_probed_at_its_own_address(gate):
    """Assert each program is probed at the address it binds, not a sibling's port."""
    services = (
        ("sep", StubService(UVICORN_PORT=9000, ALLOWED_HOSTS=["sep.example"])),
        ("inventory", StubService(UVICORN_PORT=9001)),
        ("tasks", StubService(UVICORN_PORT=9002)),
    )

    ready, probes = gate(services)

    assert ready
    assert [probe.port for probe in probes] == [9000, 9001, 9002]
    assert probes[0].allowed_hosts == ["sep.example"]


def test_the_services_share_one_budget(gate):
    """Keep the timeout shared across the three, rather than spent once per service.

    Three services on a per-service budget would hold a container start for three
    times the configured wait before beat is allowed to start degraded.
    """
    services = tuple(
        (name, StubService(UVICORN_PORT=port))
        for name, port in (("sep", 9000), ("inventory", 9001), ("tasks", 9002))
    )

    _, probes = gate(services, elapsed=10.0)

    assert probes[0].timeout == sep_settings.API_READINESS_TIMEOUT
    assert [probe.timeout for probe in probes] == [
        sep_settings.API_READINESS_TIMEOUT - offset for offset in (0.0, 10.0, 20.0)
    ]


def test_an_exhausted_budget_skips_the_rest(gate, caplog):
    """Report every listener beat did not wait for instead of stopping at the first."""
    services = (
        ("sep", StubService(UVICORN_PORT=9000)),
        ("inventory", StubService(UVICORN_PORT=9001)),
        ("tasks", StubService(UVICORN_PORT=9002)),
    )

    with caplog.at_level(logging.ERROR, logger=helper.logger.name):
        ready, probes = gate(services, elapsed=sep_settings.API_READINESS_TIMEOUT + 1.0)

    assert not ready
    assert [probe.port for probe in probes] == [9000]
    assert "inventory" in caplog.text
    assert "tasks" in caplog.text


def test_a_tls_service_is_skipped_not_probed(gate, caplog):
    """Skip a TLS listener rather than burn the budget on handshake failures.

    The probe speaks plain HTTP, so a TLS listener can never answer it with 200;
    probing one would spend the whole wait to learn nothing.
    """
    services = (
        ("sep", StubService(UVICORN_PORT=9000, SSL_CERTFILE="/certs/sep.pem")),
        ("inventory", StubService(UVICORN_PORT=9001)),
    )

    with caplog.at_level(logging.WARNING, logger=helper.logger.name):
        ready, probes = gate(services)

    assert not ready
    assert [probe.port for probe in probes] == [9001]
    assert "TLS" in caplog.text


def test_a_failed_probe_is_reported_without_stopping_the_rest(gate):
    """Keep probing after a service times out, so the log accounts for all three."""
    services = (
        ("sep", StubService(UVICORN_PORT=9000)),
        ("inventory", StubService(UVICORN_PORT=9001)),
        ("tasks", StubService(UVICORN_PORT=9002)),
    )

    ready, probes = gate(services, verdicts=(False, True, True))

    assert not ready
    assert [probe.port for probe in probes] == [9000, 9001, 9002]


def test_main_logs_the_degradation_and_returns(monkeypatch, caplog):
    """Return normally on a degraded gate: the shell goes on to exec beat."""
    monkeypatch.setattr("logging.config.dictConfig", lambda _: None)
    monkeypatch.setattr(helper, "wait_for_apis", lambda: False)

    with caplog.at_level(logging.ERROR, logger=helper.logger.name):
        helper.main()

    assert "without every HTTP API confirmed ready" in caplog.text


def test_main_is_quiet_when_every_api_is_ready(monkeypatch, caplog):
    """Leave no ERROR behind on the ordinary start."""
    monkeypatch.setattr("logging.config.dictConfig", lambda _: None)
    monkeypatch.setattr(helper, "wait_for_apis", lambda: True)

    with caplog.at_level(logging.ERROR, logger=helper.logger.name):
        helper.main()

    assert not caplog.records
