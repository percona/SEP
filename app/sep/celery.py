"""Define Celery tasks and utilities for the SEP app."""

import logging
from pathlib import Path

from asgiref.sync import async_to_sync
from sqlalchemy_celery_beat import PeriodicTask
from sqlmodel import col

from app.core.celery.crud import BasePeriodicTaskManager, IntervalScheduleManager
from app.core.celery.db import (
    get_async_session_maker as get_celery_beat_async_session_maker,
)
from app.core.celery.utils import create_celery
from app.sep.config import sep_settings
from app.sep.crud import SnippetManager
from app.sep.db import get_async_session_maker
from app.sep.models import Snippet

logger = logging.getLogger(__name__)
celery = create_celery("sep")


if sep_settings.SNIPPETS.USE_MAGIC:
    import magic

    def guess_mime_type(file_path: Path) -> str | None:
        """Guess the MIME type of a file using the `magic` library.

        :param file_path: The path to the file.
        :type file_path: Path
        :return: The MIME type of the file, or None if it cannot be determined.
        :rtype: str | None
        """
        return magic.from_file(file_path, mime=True) or None
else:
    import mimetypes

    def guess_mime_type(file_path: Path) -> str | None:
        """Guess the MIME type of a file using the file extension.

        :param file_path: The path to the file.
        :type file_path: Path
        :return: The MIME type of the file, or None if it cannot be determined.
        :rtype: str | None
        """
        return mimetypes.types_map.get(file_path.suffix)


@celery.task
def sync_snippets() -> None:
    """Define Celery task to sync snippets from `sep_setting.SNIPPETS.SNIPPETS_DIR`."""
    async_to_sync(update_snippets)()


async def update_snippets() -> None:
    """Search for new/updated/deleted snippets and creates/updates/deletes them."""
    async_session = get_async_session_maker(create_new_engine=True)
    async with async_session() as session:
        updated_snippets = []
        processed_filenames = []
        skipped_filenames = []
        created_count = 0
        for snippet_path in sep_settings.SNIPPETS.SNIPPETS_DIR.rglob("*"):
            if snippet_path.is_file():
                snippet_name = str(
                    snippet_path.relative_to(sep_settings.SNIPPETS.SNIPPETS_DIR)
                )
                processed_filenames.append(snippet_name)
                if (
                    (snippets_filter := sep_settings.SNIPPETS.FILTER_EXTENSIONS)
                    is not None
                    and (snippet_filter_value := snippet_path.suffix.lower())
                    not in snippets_filter
                ) or (
                    (snippets_filter := sep_settings.SNIPPETS.FILTER_MIME_TYPES)
                    is not None
                    and (snippet_filter_value := guess_mime_type(snippet_path))
                    not in snippets_filter
                ):
                    logger.debug(
                        "Skipping file %s due to filter (%r doesn't match %r)",
                        snippet_path,
                        snippet_filter_value,
                        snippets_filter,
                    )
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
                        "Snippet %s has changed: %s > %s",
                        created_snippet.filename,
                        created_snippet.md5_digest,
                        snippet.md5_digest,
                    )
                    created_snippet.sqlmodel_update(snippet)
                    created_snippet.meta = await Snippet.get_meta_by_path(snippet_path)
                    created_snippet.remove_approval("File contents have changed")
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


async def init_periodic_tasks_db() -> None:
    """Initialize the database with required periodic tasks."""
    celery_beat_async_session = get_celery_beat_async_session_maker()
    periodic_task_name = "sync_snippets"
    async with celery_beat_async_session() as celery_beat_session:
        schedule, _ = await IntervalScheduleManager.get_or_create(
            celery_beat_session, sep_settings.SNIPPETS.SYNC_INTERVAL
        )
        periodic_task = await BasePeriodicTaskManager.first(
            celery_beat_session, name=periodic_task_name
        )
        if periodic_task and periodic_task.schedule_model == schedule:
            return
        if periodic_task is None:
            periodic_task = PeriodicTask(
                name=periodic_task_name,
                task="app.sep.celery.sync_snippets",
                schedule_model=schedule,
            )
        if periodic_task.schedule_model != schedule:
            periodic_task.schedule_model = schedule
        celery_beat_session.add(periodic_task)
        await celery_beat_session.commit()
