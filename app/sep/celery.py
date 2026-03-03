# Copyright (C) 2025 Percona LLC
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

"""Define Celery tasks and utilities for the SEP app."""

import logging
from pathlib import Path

from sqlmodel import col

from app.celery import celery
from app.sep.db import get_async_session_maker
from app.sep.snippets.config import SnippetFilterType, snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import Snippet
from app.sep.snippets.utils import guess_mime_type

logger = logging.getLogger(__name__)


@celery.task
def sync_snippets() -> None:
    """Define Celery task to sync snippets from `sep_setting.SNIPPETS.SNIPPETS_DIR`."""
    celery.loop.run_until_complete(update_snippets())


async def update_snippets() -> None:
    """Search for new/updated/deleted snippets and creates/updates/deletes them."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        updated_snippets = []
        processed_filenames = []
        skipped_filenames = []
        created_count = 0
        for snippet_path in snippets_settings.SNIPPETS_DIR.rglob("*"):
            if snippet_path.is_file():
                snippet_name = str(
                    snippet_path.relative_to(snippets_settings.SNIPPETS_DIR)
                )
                processed_filenames.append(snippet_name)
                if should_skip_snippet(snippet_path):
                    skipped_filenames.append(snippet_name)
                    continue
                snippet = await Snippet.from_path(snippet_path)
                logger.debug(
                    "Processing file %s: %s", snippet_path, snippet.model_dump()
                )
                created_snippet, created = await SnippetManager.get_or_create(
                    session, snippet, {"filename"}
                )
                if created:
                    logger.debug("New snippet created: %s", created_snippet.filename)
                    created_count += 1
                elif created_snippet.md5_digest != snippet.md5_digest:
                    logger.debug(
                        "Snippet %s has changed: %s [before] != %s [now]",
                        created_snippet.filename,
                        created_snippet.md5_digest,
                        snippet.md5_digest,
                    )
                    await created_snippet.update_from_snippet(snippet)
                    updated_snippets.append(created_snippet)
        if created_count:
            logger.info("Added %s new snippets", created_count)
        if updated_snippets:
            logger.info("Updating %s modified snippets", len(updated_snippets))
            await SnippetManager.save_batch(
                session, *updated_snippets, flag_modified_fields=["meta"]
            )
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
