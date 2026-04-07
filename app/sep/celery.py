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

"""Define Celery tasks and utilities for the SEP app."""

import asyncio
import logging
from pathlib import Path

from sqlmodel import col

from app.celery import celery
from app.sep.config import sep_settings
from app.sep.db import get_async_session_maker
from app.sep.plugins.alerts.crud import AlertBackupManager
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


@celery.task
def generate_health_report() -> None:
    """Define Celery task to generate a periodic PMM health report."""
    celery.loop.run_until_complete(_generate_health_report())


async def _generate_health_report() -> None:
    """Generate a health report from PMM, log it, and optionally upload to ServiceNow.

    When ``REPORT_UPLOAD`` is fully configured the report is rendered to PDF
    and uploaded.  Upload failures are logged but do not prevent the task from
    completing.
    """
    from app.sep.config import sep_settings
    from app.sep.plugins.report.deps import get_pmm_api
    from app.sep.plugins.report.service import (
        generate_pdf_report,
        generate_report,
        upload_pdf_report,
    )

    pmm_api = await get_pmm_api()
    if pmm_api is None:
        logger.warning("PMM not configured, skipping health report generation")
        return

    try:
        report = await generate_report(pmm_api)
        logger.info(
            "Health report generated: %s (%d nodes, %d services)",
            report.metadata.title,
            report.monitored.total_nodes,
            report.monitored.total_services,
        )
    except Exception:
        logger.exception("Failed to generate health report")
        return

    if not sep_settings.REPORT_UPLOAD.is_configured:
        return

    try:
        pdf_bytes = await generate_pdf_report(report)
        result = await upload_pdf_report(report, pdf_bytes)
        logger.info("Health report uploaded to ServiceNow: %s", result)
    except Exception:
        logger.exception("Failed to upload health report to ServiceNow")


@celery.task
def backup_alert_config() -> None:
    """Define Celery task to back up PMM alert configuration."""
    celery.loop.run_until_complete(_backup_alert_config())


async def _backup_alert_config() -> None:
    """Fetch alert configuration from PMM and store as a backup."""
    from app.sep.plugins.alerts.backup import AlertBackup
    from app.sep.plugins.alerts.deps import get_pmm_api

    pmm_api = await get_pmm_api()
    if pmm_api is None:
        logger.warning("PMM not configured, skipping alert backup")
        return

    try:
        (
            templates,
            rules,
            contact_points,
            notification_policy,
            folders,
        ) = await asyncio.gather(
            pmm_api.list_templates(),
            pmm_api.list_rules(),
            pmm_api.list_contact_points(),
            pmm_api.get_notification_policy(),
            pmm_api.list_folders(),
        )
    except Exception:
        logger.exception("Failed to fetch alert configuration from PMM")
        return

    data = {
        "templates": sorted(
            (t.model_dump() for t in templates), key=lambda t: t["name"]
        ),
        "rules": sorted((r.model_dump() for r in rules), key=lambda r: r["uid"]),
        "contact_points": sorted(
            (cp.model_dump() for cp in contact_points), key=lambda cp: cp["uid"]
        ),
        "notification_policy": notification_policy.model_dump(),
        "folders": sorted((f.model_dump() for f in folders), key=lambda f: f["uid"]),
    }
    metadata = {
        "template_count": len(templates),
        "rule_count": len(rules),
        "contact_point_count": len(contact_points),
        "folder_count": len(folders),
    }

    async_session = get_async_session_maker()
    async with async_session() as session:
        recent = await AlertBackupManager.list_recent(session, limit=1)
        if recent and recent[0].data == data:
            logger.debug("Alert config unchanged, skipping backup")
            return

        backup = AlertBackup(data=data, metadata_=metadata)
        await AlertBackupManager.save(session, backup)

        retention = sep_settings.PMM.backup_retention
        all_backups = await AlertBackupManager.list(session)
        if len(all_backups) > retention:
            ids_to_delete = [b.id for b in all_backups[retention:]]
            await AlertBackupManager.delete_where(
                session, col(AlertBackup.id).in_(ids_to_delete)
            )
