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

"""Report per-entity sync outcomes to the inventory service."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Final

from fastapi import HTTPException

from app.core.requests import RemoteAPI
from app.core.utils.date_time import utc_now
from app.inventory.models import SyncOutcomeEnum
from app.sep.inventory import CreatedEntity
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.sync.constants import INVENTORY_PATH_SEGMENTS
from app.sep.sync.exceptions import (
    SyncFailError,
    SyncInstanceAlreadyInProgressError,
    SyncItemAlreadyInProgressError,
)

logger = logging.getLogger(__name__)


#: The exceptions whose full message may be stored on ``last_sync_error``.
#:
#: An allowlist rather than a denylist, and named per class rather than by
#: hierarchy: a ``SyncError`` subclass added later must be opted in deliberately
#: instead of inheriting persistence from its base. Every member here
#: interpolates only sync bookkeeping — the ``SyncItem`` an attempt was for.
#: ``ExecutorHostNotFoundError`` is deliberately absent: its message carries the
#: whole executor-host map from the Tasks API, which the inventory read routes
#: would then expose to any authenticated caller.
_MESSAGE_SAFE_ERRORS: Final = (
    SyncFailError,
    SyncInstanceAlreadyInProgressError,
    SyncItemAlreadyInProgressError,
)


def _describe_sync_error(error: Exception) -> str:
    """Summarize an exception for storage on an entity's ``last_sync_error``.

    The field is durable and readable through the inventory read routes, so the
    summary carries a message only for the exceptions listed in
    :data:`_MESSAGE_SAFE_ERRORS`. Everything else is reduced to its type name: a
    third-party exception's message is arbitrary text this code never inspected
    — a ``ValidationError`` echoes the offending input, a driver error can carry
    a DSN — and no redaction pass can be trusted over an open set. Nothing is
    lost by the reduction: only the description is persisted, and the exception
    itself is re-raised out of :meth:`SyncHealthReporter.record` to the boundary
    that logs it with its traceback.

    The result is non-empty but not length-bounded; the inventory service
    truncates it to the column's contract when it stores it.

    :param error: The exception that ended the sync attempt.
    :return: A non-empty description carrying no caller-supplied text.
    """
    if isinstance(error, HTTPException):
        return f"{type(error).__name__}: HTTP {error.status_code}"
    if isinstance(error, _MESSAGE_SAFE_ERRORS):
        return f"{type(error).__name__}: {error}"
    return type(error).__name__


class SyncHealthAttempt:
    """Track whether a sync attempt reached a real comparison against source.

    Defaults to not-compared so a path that forgets to mark it records nothing,
    which is the safe direction: an unwritten column reads as stale, never as
    freshly confirmed.

    :ivar compared: Whether the block held real source data and synced from it.
    """

    def __init__(self) -> None:
        self.compared = False

    def mark_compared(self) -> None:
        """Record that source data was in hand and the entity was synced from it."""
        self.compared = True


class SyncHealthReporter:
    """Report per-entity sync outcomes to the inventory service.

    Mechanism only: which entity levels a syncer mirrors is policy, declared on
    the syncer class (``BaseSyncer.mirrors_entity_levels``) and handed in here.

    :param inventory_api: The inventory service client the outcomes post to.
    :param mirrored_levels: The entity levels whose attempts are recorded;
        every other level passes through unrecorded.
    """

    def __init__(
        self,
        inventory_api: RemoteAPI,
        mirrored_levels: frozenset[SyncInventoryEntityTypeEnum],
    ) -> None:
        self._inventory_api = inventory_api
        self._mirrored_levels = mirrored_levels

    @asynccontextmanager
    async def record(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        created_entity: CreatedEntity,
    ) -> AsyncGenerator[SyncHealthAttempt, None]:
        """Write the entity's sync-health columns from this attempt's outcome.

        Nests inside ``manage_sync_item`` so a failure is recorded before that
        boundary marks the SyncItem failed and raises under ``break_on_error``.
        A failure is recorded unconditionally — entering this block at a
        mirrored level *is* the genuine attempt, and a ``fetch_*`` that raises
        is exactly the failure worth reporting. A success is recorded only once
        the block marked itself compared, which is what excludes the
        filtered-out early return that leaves ``manage_sync_item``'s clean-exit
        path indistinguishable from a real sync.

        A ``SyncFailError`` is the exception: it can only come from a *nested*
        level, because this level's own boundary raises it after this block has
        already exited. The syncers walk to children from inside the parent's
        ``perform_*_sync``, so a child's failure passes through here — and
        whether it does at all depends on ``break_on_error``, since otherwise
        the child's own boundary swallows it. Attributing it to this entity
        would make the columns describe an identical outcome differently in the
        two modes, and would report a parent as failing whose own mirrored
        fields were confirmed. The child records its own failure on its own row.

        :param entity_type: The level being synced.
        :param created_entity: The entity being synced.
        :return: The marker the block flags once it holds real source data.
        """
        attempt = SyncHealthAttempt()
        if entity_type not in self._mirrored_levels:
            yield attempt
            return
        attempted_at = utc_now()
        try:
            yield attempt
        except SyncFailError as exc:
            await self._post(
                entity_type,
                created_entity,
                attempted_at,
                None if attempt.compared else exc,
            )
            raise
        except Exception as exc:
            await self._post(entity_type, created_entity, attempted_at, exc)
            raise
        if attempt.compared:
            await self._post(entity_type, created_entity, attempted_at, None)

    async def _post(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        created_entity: CreatedEntity,
        attempted_at: datetime,
        error: Exception | None,
    ) -> None:
        """Report one entity's sync outcome to the inventory service.

        Best-effort: a bookkeeping write must not fail an otherwise-healthy
        sync item, and losing one leaves the entity looking stale rather than
        falsely fresh.

        :param entity_type: The level being reported.
        :param created_entity: The entity being reported.
        :param attempted_at: When this attempt began, captured before the block
            ran so the inventory service orders by attempt, not by arrival.
        :param error: The exception that ended the attempt, or None on success.
        """
        outcome = (
            {"outcome": SyncOutcomeEnum.SUCCESS}
            if error is None
            else {
                "outcome": SyncOutcomeEnum.FAILURE,
                "error": _describe_sync_error(error),
            }
        )
        payload = {"attempted_at": attempted_at.isoformat(), **outcome}
        try:
            await self._inventory_api.post(
                f"/{INVENTORY_PATH_SEGMENTS[entity_type]}/{created_entity.id}"
                "/sync-health",
                json=payload,
            )
        except Exception:
            logger.exception(
                "Failed to record sync health for %s %s",
                entity_type.name,
                created_entity.id,
            )
