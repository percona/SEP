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

"""Define Celery tasks for the snippets app.

This module is registered through the Celery ``include`` list so its
``@owned_by("snippets")`` task registers at worker startup.
"""

import logging
from pathlib import Path

from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.celery import celery
from app.sep.app_drain import owned_by, should_cancel
from app.sep.apps.snippets.builtin_manifest import (
    load_builtin_checksum_manifest,
    manifest_relative_path,
    sha256_file,
)
from app.sep.apps.snippets.constants import (
    BUILTIN_APPROVAL_REASON,
    BUILTIN_APPROVAL_USER_ID,
    BUILTIN_CHECKSUM_MANIFEST,
)
from app.sep.db import get_async_session_maker
from app.sep.snippets.config import SnippetFilterType, snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import Snippet
from app.sep.snippets.utils import guess_mime_type

logger = logging.getLogger(__name__)

_CONTENT_CHANGED_REASON = "File contents have changed"


@owned_by("snippets")
@celery.task
def sync_snippets() -> None:
    """Define Celery task to sync snippets from `sep_setting.SNIPPETS.SNIPPETS_DIR`."""
    celery.loop.run_until_complete(update_snippets())


async def update_snippets() -> None:
    """Sync snippet files into the database and apply built-in auto-approval.

    Skip the checksum manifest file. Create, update, or delete snippet rows to
    match disk, and auto-approve manifest-matching files when that setting is
    enabled, without restoring administrator revocations.
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        content_changed_snippets: list[Snippet] = []
        approval_snippets: list[Snippet] = []
        processed_filenames: list[str] = []
        skipped_filenames: list[str] = []
        created_count = 0
        auto_approve_enabled = snippets_settings.AUTO_APPROVE_BUILTIN_SNIPPETS
        manifest = (
            await load_builtin_checksum_manifest(snippets_settings.SNIPPETS_DIR)
            if auto_approve_enabled
            else {}
        )
        for snippet_path in snippets_settings.SNIPPETS_DIR.rglob("*"):
            if await should_cancel("snippets", session=session):
                logger.info("Snippets app disabling; stopping snippet sync early.")
                return
            if not snippet_path.is_file():
                continue
            snippet_name = manifest_relative_path(
                snippet_path, snippets_settings.SNIPPETS_DIR
            )
            if snippet_name == BUILTIN_CHECKSUM_MANIFEST:
                continue
            processed_filenames.append(snippet_name)
            if should_skip_snippet(snippet_path):
                skipped_filenames.append(snippet_name)
                continue
            created = await _sync_snippet_file(
                session,
                snippet_path,
                snippet_name,
                manifest,
                content_changed_snippets,
                approval_snippets,
                auto_approve_enabled=auto_approve_enabled,
            )
            if created:
                created_count += 1
        if await should_cancel("snippets", session=session):
            logger.info("Snippets app disabling; skipping post-sync snippet writes.")
            return
        await _persist_snippet_sync_batches(
            session,
            created_count=created_count,
            content_changed_snippets=content_changed_snippets,
            approval_snippets=approval_snippets,
        )
        await _delete_unsynced_snippets(session, processed_filenames, skipped_filenames)


async def _persist_snippet_sync_batches(
    session: AsyncSession,
    *,
    created_count: int,
    content_changed_snippets: list[Snippet],
    approval_snippets: list[Snippet],
) -> None:
    """Log sync totals and batch-save content-change and approval-only rows.

    :param session: The active database session.
    :param created_count: Number of new snippet rows created during this sync.
    :param content_changed_snippets: Rows whose file contents changed.
    :param approval_snippets: Rows that only need approval fields persisted.
    """
    if created_count:
        logger.info("Added %s new snippets", created_count)
    if content_changed_snippets:
        logger.info("Updating %s modified snippets", len(content_changed_snippets))
        await SnippetManager.save_batch(
            session, *content_changed_snippets, flag_modified_fields=["meta"]
        )
    if approval_snippets:
        logger.info(
            "Auto-approving %s snippets from built-in checksum manifest",
            len(approval_snippets),
        )
        await SnippetManager.save_batch(session, *approval_snippets)


async def _sync_snippet_file(
    session: AsyncSession,
    snippet_path: Path,
    snippet_name: str,
    manifest: dict[str, str],
    content_changed_snippets: list[Snippet],
    approval_snippets: list[Snippet],
    *,
    auto_approve_enabled: bool,
) -> bool:
    """Sync one snippet file into the database and apply approval policy.

    :param session: The active database session.
    :param snippet_path: Absolute path to the snippet file on disk.
    :param snippet_name: Filename relative to the snippets directory.
    :param manifest: Built-in checksum mapping of filename to SHA-256 digest.
    :param content_changed_snippets: Mutable list collecting rows whose file
        contents changed (caller batch-saves with ``meta`` flagged modified).
    :param approval_snippets: Mutable list collecting rows that only need
        approval fields persisted (new auto-approvals and upgrade-path approvals).
    :param auto_approve_enabled: Whether manifest-matched auto-approval is enabled.
    :return: ``True`` when a new snippet row was created.
    """
    snippet = await Snippet.from_path(snippet_path)
    logger.debug("Processing file %s: %s", snippet_path, snippet.model_dump())
    manifest_match = auto_approve_enabled and manifest.get(
        snippet_name
    ) == await sha256_file(snippet_path)
    created_snippet, created = await SnippetManager.get_or_create(
        session, snippet, {"filename"}
    )
    if created:
        logger.debug("New snippet created: %s", created_snippet.filename)
        if manifest_match:
            _auto_approve(created_snippet)
            approval_snippets.append(created_snippet)
        return True

    if created_snippet.md5_digest != snippet.md5_digest:
        logger.debug(
            "Snippet %s has changed: %s [before] != %s [now]",
            created_snippet.filename,
            created_snippet.md5_digest,
            snippet.md5_digest,
        )
        human_revoked = created_snippet.is_human_revoked
        await created_snippet.update_from_snippet(snippet)
        _apply_content_change_approval(
            created_snippet,
            manifest_match=manifest_match,
            human_revoked=human_revoked,
        )
        content_changed_snippets.append(created_snippet)
    elif (
        manifest_match
        and not created_snippet.is_approved
        and not created_snippet.is_human_revoked
    ):
        _auto_approve(created_snippet)
        approval_snippets.append(created_snippet)
    return False


def _auto_approve(snippet: Snippet) -> None:
    """Mark ``snippet`` as automatically approved from the built-in manifest.

    :param snippet: The snippet row to approve.
    """
    snippet.approve(BUILTIN_APPROVAL_REASON, BUILTIN_APPROVAL_USER_ID)


def _apply_content_change_approval(
    snippet: Snippet,
    *,
    manifest_match: bool,
    human_revoked: bool,
) -> None:
    """Apply approval policy after a content change.

    Leave approval state unchanged when an administrator revoked it. Otherwise
    auto-approve on a manifest match, or clear approval when the digest no
    longer matches.

    :param snippet: The snippet row whose file contents just changed.
    :param manifest_match: Whether the new contents match the built-in manifest.
    :param human_revoked: Whether an administrator had revoked approval before the
        content update.
    """
    if human_revoked:
        return
    if manifest_match:
        _auto_approve(snippet)
    else:
        snippet.remove_approval(_CONTENT_CHANGED_REASON, None)


async def _delete_unsynced_snippets(
    session: AsyncSession,
    processed_filenames: list[str],
    skipped_filenames: list[str],
) -> None:
    """Delete snippet rows whose files are gone from disk or now filtered out."""
    delete_result = await SnippetManager.delete_where(
        session, col(Snippet.filename).not_in(processed_filenames)
    )
    if delete_result.rowcount:
        logger.info(
            "Deleted %s snippets not found in filesystem", delete_result.rowcount
        )
    delete_result = await SnippetManager.delete_where(
        session,
        col(Snippet.filename).in_(skipped_filenames),
        col(Snippet.approved_at).is_(None),
    )
    if delete_result.rowcount:
        logger.info(
            "Deleted %s non-approved snippets that don't match the defined filters",
            delete_result.rowcount,
        )


def should_skip_snippet(snippet_path: Path) -> bool:
    """Determine if a snippet file should be skipped based on defined filters.

    :param snippet_path: The path to the snippet file.
    :type snippet_path: Path
    :return: True if the snippet should be skipped, False otherwise.
    :rtype: bool
    """
    if snippets_settings.SYNC_FILTER is not None:
        extension = snippet_path.suffix.lower()
        mime = guess_mime_type(snippet_path)
        if (
            extension,
            SnippetFilterType.EXTENSION,
        ) not in snippets_settings.SYNC_FILTER and (
            mime,
            SnippetFilterType.MIME_TYPE,
        ) not in snippets_settings.SYNC_FILTER:
            logger.debug(
                "Skipping file %s since no match found in defined filters (%r, %r)",
                snippet_path,
                extension,
                mime,
            )
            return True
    return False
