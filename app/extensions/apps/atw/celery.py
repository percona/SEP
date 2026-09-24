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

"""Define Celery tasks for the ATW app.

This module is registered through the Celery ``include`` list so its
``@owned_by("atw")`` tasks register at worker startup. Neither task is bound: a
send's status lives in its ``atw_send_log`` row, not in Celery's result backend,
which expires long before an operator stops caring about a failed send.
"""

import logging
from uuid import UUID

from app.celery import celery
from app.extensions.app_drain import owned_by
from app.extensions.apps.atw.config import atw_settings
from app.extensions.apps.atw.reconcile import reconcile_executions
from app.extensions.apps.atw.send import (
    fail_stale_sends,
    purge_expired_bundles,
    run_send,
)

logger = logging.getLogger(__name__)


@owned_by("atw")
@celery.task
def send_incident_diagnostics(send_log_id: str) -> None:
    """Build and deliver the diagnostics bundle one send log describes.

    :param send_log_id: The ``atw_send_log`` row driving this attempt.
    """
    celery.loop.run_until_complete(run_send(UUID(send_log_id)))


@owned_by("atw")
@celery.task
def purge_atw_bundles() -> None:
    """Reap expired staged bundles and fail sends whose worker was lost.

    Both halves of the housekeeping share one schedule: they bound the same
    feature's leftovers -- bytes on disk and rows the UI would otherwise poll
    forever.
    """
    removed = purge_expired_bundles(atw_settings.bundle_ttl)
    if removed:
        logger.info("Purged %d expired diagnostics bundle(s)", removed)
    celery.loop.run_until_complete(fail_stale_sends(atw_settings.stale_send_after))


@owned_by("atw")
@celery.task
def reconcile_atw_executions() -> None:
    """Resolve run outcomes the ``run_result_recorder`` hook never observed.

    Kept separate from ``purge_atw_bundles`` because it is not housekeeping: the
    purge bounds leftovers, while this is the only mechanism that makes the failed
    count correct for historical runs and for the three terminal transitions the
    hook is documented not to see.
    """
    celery.loop.run_until_complete(
        reconcile_executions(atw_settings.reconcile_batch_size)
    )
