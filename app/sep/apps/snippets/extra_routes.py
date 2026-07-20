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

"""Carry the snippets surface the ``ScriptSource`` seam does not derive.

The framework derives listing, per-snippet schema, history, and execute from
:data:`~app.sep.apps.snippets.script_source.snippet_source`; the auxiliary
verbs (approval, manual refresh, preview/download) stay hand-written and are
threaded into the app as ``extra_routes``. Handler names are preserved so the
OpenAPI operation IDs of these non-derived routes stay byte-identical across the
migration.
"""

import logging

from fastapi import APIRouter, Response
from fastapi import status as http_status
from fastapi.responses import FileResponse
from sqlmodel import col

from app.core.exceptions import HTTPUnprocessableEntityException
from app.core.utils import utc_now
from app.sep.app_drain import track_app_task
from app.sep.apps.framework.script_helpers import build_script_preview
from app.sep.apps.framework.script_source import ScriptPreviewResponse
from app.sep.apps.snippets.celery import update_snippets
from app.sep.apps.snippets.deps import (
    IsManualSyncEnabled,
    SnippetBatchExistenceDep,
    SnippetDep,
)
from app.sep.apps.snippets.models import (
    BatchApprovalResponse,
    build_snippet_response,
    RefreshResponse,
    SnippetResponse,
)
from app.sep.deps import ApiAdminUser, IsApiAuthenticated, SessionDep
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import Snippet
from app.sep.snippets.utils import guess_mime_type

logger = logging.getLogger(__name__)


maintenance_router = APIRouter()


@maintenance_router.post(
    "/refresh", dependencies=[IsApiAuthenticated, IsManualSyncEnabled]
)
async def snippets_api_refresh(
    user: ApiAdminUser, session: SessionDep
) -> RefreshResponse:
    """Refresh the snippets cache from disk.

    Admin-only and additionally gated by manual sync being enabled.
    Mirrors the legacy Jinja2 ``POST /snippets/refresh`` route.

    :param user: The authenticated admin performing the refresh.
    :type user: User
    :param session: The SEP database session.
    :return: A response carrying the UTC timestamp of the refresh.
    :rtype: RefreshResponse
    """
    async with track_app_task(session, "snippets"):
        await update_snippets()
    logger.info("Snippets refreshed via JSON API by %s", user.username)
    return RefreshResponse(refreshed_at=utc_now())


artifact_router = APIRouter()


@artifact_router.get(
    "/snippet/preview",
    dependencies=[IsApiAuthenticated],
)
async def snippets_api_script_preview(snippet: SnippetDep) -> ScriptPreviewResponse:
    """Return the snippet's preview content with a highlighter language hint.

    :param snippet: The snippet whose preview is requested.
    :type snippet: Snippet
    :return: The preview content alongside metadata about it.
    :rtype: ScriptPreviewResponse
    :raises HTTPUnprocessableEntityException: When the snippet contains
        bytes that cannot be decoded as UTF-8.
    """
    try:
        return await build_script_preview(snippet)
    except UnicodeDecodeError as exc:
        raise HTTPUnprocessableEntityException(
            detail=(
                f"Snippet {snippet.filename!r} contains non-UTF-8 bytes; "
                "preview is unavailable."
            ),
        ) from exc


@artifact_router.get(
    "/snippet/download",
    dependencies=[IsApiAuthenticated],
)
async def snippets_api_download(snippet: SnippetDep) -> FileResponse:
    """Stream the raw snippet file as a download attachment.

    Returns the on-disk source verbatim — full bash/Python body plus its
    YAML frontmatter — so end users can save the file locally without
    being capped by the preview truncation limits. The
    ``SnippetDep`` dependency already validates both the DB row and the
    on-disk file, so a missing snippet or missing file surfaces as 404.

    :param snippet: The snippet whose raw file is requested.
    :type snippet: Snippet
    :return: The snippet file streamed as ``attachment; filename=...``
        with a MIME type guessed from the on-disk path.
    :rtype: FileResponse
    """
    return FileResponse(
        snippet.path,
        filename=snippet.filename,
        media_type=guess_mime_type(snippet.path),
    )


approval_router = APIRouter()


@approval_router.put("/snippet/approval", dependencies=[IsApiAuthenticated])
async def snippets_api_approve(
    snippet: SnippetDep, user: ApiAdminUser, session: SessionDep
) -> SnippetResponse:
    """Approve a single snippet (idempotent).

    Re-approving an already-approved snippet returns ``200`` with the
    current state — ``approved_at`` is *not* overwritten so the audit
    trail is preserved.

    :param snippet: The snippet whose approval is being set.
    :type snippet: Snippet
    :param user: The authenticated admin performing the action.
    :type user: User
    :param session: The active database session.
    :type session: AsyncSession
    :return: The snippet entity after the call, including approval state.
    :rtype: SnippetResponse
    """
    if not snippet.is_approved:
        snippet.approve(f"Approved by {user.username}", str(user.id))
        await SnippetManager.save(session, snippet)
        logger.info("Snippet %r approved by %s", snippet.filename, user.username)
    return build_snippet_response(snippet)


@approval_router.delete(
    "/snippet/approval",
    status_code=http_status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[IsApiAuthenticated],
)
async def snippets_api_remove_approval(
    snippet: SnippetDep, user: ApiAdminUser, session: SessionDep
) -> None:
    """Remove approval from a single snippet (idempotent).

    Removing an approval that doesn't exist is a no-op ``204``. The
    snippet missing → ``404`` (handled by ``SnippetDep``); approval
    missing → ``204``.

    :param snippet: The snippet whose approval is being cleared.
    :type snippet: Snippet
    :param user: The authenticated admin performing the action.
    :type user: User
    :param session: The active database session.
    :type session: AsyncSession
    :return: An empty 204 response.
    :rtype: Response
    """
    if snippet.is_approved:
        snippet.remove_approval(f"Approval removed by {user.username}", str(user.id))
        await SnippetManager.save(session, snippet)
        logger.info(
            "Snippet %r approval removed by %s", snippet.filename, user.username
        )


@approval_router.patch("/approvals", dependencies=[IsApiAuthenticated])
async def snippets_api_batch_approve(
    existence: SnippetBatchExistenceDep,
    user: ApiAdminUser,
    session: SessionDep,
) -> BatchApprovalResponse:
    """Approve a set of snippets atomically (idempotent partial-update).

    Reject the whole batch with ``400`` and a
    :class:`BatchApprovalErrorResponse` payload when any filename has no
    DB row or its file is missing on disk. Filenames that are already
    approved when the call starts are reported in
    ``skipped_already_approved`` — not as errors. The atomic write uses
    ``approved_at IS NULL`` as a CAS filter so two concurrent admins
    cannot double-approve.

    :param existence: Pre-validated batch existence result from the dependency.
    :type existence: SnippetBatchExistenceResult
    :param user: The authenticated admin performing the action.
    :type user: User
    :param session: The active database session.
    :type session: AsyncSession
    :return: The success payload listing approved + skipped filenames.
    :rtype: BatchApprovalResponse
    :raises HTTPBadRequestException: On hard-error precheck failures with
        a :class:`BatchApprovalErrorResponse` body.
    """
    pre_already_approved = []
    to_approve = []
    for snippet in existence.snippets:
        if snippet.is_approved:
            pre_already_approved.append(snippet.filename)
        else:
            to_approve.append(snippet.filename)
    pre_already_approved.sort()
    to_approve.sort()
    approved: list[str] = []
    if to_approve:
        approved_rows = await SnippetManager.update_where(
            session,
            {
                "approved_at": utc_now(),
                "updated_by": str(user.id),
                "reason": f"Batch approved by {user.username}",
            },
            col(Snippet.filename).in_(to_approve),
            col(Snippet.approved_at).is_(None),
            returning=["filename"],
        )
        approved = sorted(approved_rows)

    raced_out = sorted(set(to_approve) - set(approved))
    skipped = sorted(pre_already_approved + raced_out)
    logger.info(
        "Batch-approve via JSON API by %s: approved=%s skipped=%s",
        user.username,
        approved,
        skipped,
    )
    return BatchApprovalResponse(
        approved=approved,
        skipped_already_approved=skipped,
    )
