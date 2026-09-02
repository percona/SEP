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
"""Hold the side-car's Celery beat until its HTTP APIs answer their health probe.

``supervisord.conf`` runs this immediately before the ``celery-beat`` command.
supervisord orders its spawn calls by ``priority`` but never waits for readiness —
it has no ``depends_on``, which is why the alembic one-shots carry their own
``until nc -z`` loops and the API programs carry ``wait_for_schema.sh``.
``celery-beat`` is therefore spawned in the same tick as the
priority-20 API programs it is ordered behind, and those need seconds to accept
connections. Beat's schedule is persisted by the ``sqlalchemy`` scheduler, so
anything already overdue is dispatched about a second in, and a periodic task whose
first act is to call SEP's own API through ``INVENTORY_ENDPOINT`` / ``TASKS_ENDPOINT``
fails on connect through no fault of its own. That is the side-car form of the race
:func:`app.main.start_celery_beat` closes for ``python -m app.main --start-celery``.

Beat starts regardless of the outcome, so this exits ``0`` in every case:
scheduling nothing at all until an operator notices is a worse outcome than the
connect error being guarded against. The ``celery-worker`` program stays ungated —
it idles harmlessly until a task arrives.

All three listeners are waited on, not only the two a periodic task dials: the
``sep`` service's lifespan is what seeds the beat schedule
(:func:`app.sep.db.seed.init_sep_db`), so beat starting behind it also starts
against a seeded, gating-applied schedule.

Readiness is :func:`app.core.health.wait_for_api_ready`, the same gate the
``--start-celery`` path uses, so the two topologies cannot drift onto different
definitions of ready. Addresses come from the application's own settings classes
rather than being re-derived, so what is probed here is what the three supervised
API programs bind.
"""

import logging
import logging.config
from time import monotonic

from app.core.config import BaseYamlAppSettings, settings
from app.core.health import wait_for_api_ready
from app.inventory.config import inventory_settings
from app.sep.config import sep_settings
from app.tasks.config import tasks_settings

logger = logging.getLogger(__name__)

GATED_SERVICES: tuple[tuple[str, BaseYamlAppSettings], ...] = (
    ("sep", sep_settings),
    ("inventory", inventory_settings),
    ("tasks", tasks_settings),
)


def wait_for_apis() -> bool:
    """Wait for every gated service to answer ``GET /health`` with ``200``.

    The services share a single budget — ``SEP.API_READINESS_TIMEOUT``, the knob the
    ``--start-celery`` gate already exposes — rather than one each, so a container
    start cannot spend it three times over. A service that has run out of budget is
    still reported, so the log names every listener beat did not wait for.

    A service configured for TLS is skipped rather than probed: the probe speaks
    plain HTTP, and dialling a TLS listener with it would burn the whole budget on
    handshake failures that can never become a ``200``.

    :return: ``True`` when every gated service answered ``200``, ``False`` when any
        was skipped or ran out of budget.
    """
    deadline = monotonic() + sep_settings.API_READINESS_TIMEOUT
    all_ready = True
    for name, service in GATED_SERVICES:
        if service.SSL_CERTFILE or service.SSL_KEYFILE:
            logger.warning(
                "Not waiting for the %s API: it is configured for TLS and this probe "
                "speaks plain HTTP.",
                name,
            )
            all_ready = False
            continue
        remaining = deadline - monotonic()
        if remaining <= 0:
            logger.error(
                "Readiness budget exhausted before the %s API was probed.", name
            )
            all_ready = False
            continue
        if not wait_for_api_ready(
            service.UVICORN_HOST,
            service.UVICORN_PORT,
            allowed_hosts=service.ALLOWED_HOSTS,
            timeout=remaining,
            interval=sep_settings.API_READINESS_POLL_INTERVAL,
        ):
            all_ready = False
    return all_ready


def main() -> None:
    """Run the readiness wait, logging the degradation when it does not complete.

    Logging is configured here rather than inherited: supervisord starts this in a
    fresh process that has run no ``dictConfig``, and the gate's own log lines are
    the only account an operator gets of why beat has not started yet.
    """
    logging.config.dictConfig(settings.LOGGING_CONFIG)
    if not wait_for_apis():
        logger.error(
            "Starting Celery beat without every HTTP API confirmed ready. An overdue "
            "periodic task that calls SEP's own API may fail to connect on its first "
            "run."
        )


if __name__ == "__main__":
    main()
