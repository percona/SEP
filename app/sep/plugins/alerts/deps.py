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

"""Define dependencies for the alerts plugin."""

import logging
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import Depends
from fastapi.exceptions import HTTPException

from app.core.config import settings
from app.sep.clients.pmm import NotificationPolicy, PMMRemoteAPI
from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, SessionDep
from app.sep.plugins.alerts.backup import AlertBackup
from app.sep.plugins.alerts.crud import AlertBackupManager
from app.sep.plugins.alerts.loader import get_alert_templates
from app.sep.plugins.alerts.models import AlertTemplate, ServiceType

logger = logging.getLogger(__name__)

AlertTemplatesDep = Annotated[
    Mapping[ServiceType, tuple[AlertTemplate, ...]], Depends(get_alert_templates)
]


async def get_pmm_api() -> PMMRemoteAPI | None:
    """Return a `PMMRemoteAPI` client, or `None` when PMM is not configured.

    :return: The PMM API client, or `None` if endpoint or API key is missing.
    :rtype: PMMRemoteAPI | None
    """
    if not sep_settings.PMM.endpoint or not sep_settings.PMM.api_key:
        return None
    return await settings.get_remote_api(
        PMMRemoteAPI,
        endpoint=sep_settings.PMM.endpoint,
        api_key=sep_settings.PMM.api_key,
        verify_ssl=sep_settings.PMM.verify_ssl,
    )


PMMAPIDep = Annotated[PMMRemoteAPI | None, Depends(get_pmm_api)]


async def get_pmm_present_names(pmm_api: PMMAPIDep) -> set[str] | None:
    """Return names of alert templates present in PMM.

    Fetch all templates from the PMM API in a single batch call and extract
    their names into a set. Return `None` when the PMM client is unavailable
    or when the API call fails, enabling graceful degradation in the UI.

    :param pmm_api: The PMM API client dependency, or `None` if PMM is not
        configured.
    :type pmm_api: PMMRemoteAPI | None
    :return: A set of template names present in PMM, or `None` on failure.
    :rtype: set[str] | None
    """
    if pmm_api is None:
        return None
    try:
        templates = await pmm_api.list_templates()
        return {t.name for t in templates}
    except (HTTPException, OSError):
        logger.warning("Failed to fetch PMM alert templates", exc_info=True)
        return None


PMMPresentNamesDep = Annotated[set[str] | None, Depends(get_pmm_present_names)]


async def get_recent_backups(session: SessionDep) -> list[AlertBackup]:
    """Return the most recent alert backups for the sidebar widget.

    :param session: The async database session.
    :type session: SessionDep
    :return: A list of recent alert backups, ordered by creation date descending.
    :rtype: list[AlertBackup]
    """
    return await AlertBackupManager.list(session)


RecentBackupsDep = Annotated[list[AlertBackup], Depends(get_recent_backups)]


async def get_alerts_index_context(
    context: DefaultContext,
    alert_templates: AlertTemplatesDep,
    pmm_present_names: PMMPresentNamesDep,
    recent_backups: RecentBackupsDep,
) -> dict[str, Any]:
    """Assemble the template context for the alerts plugin index view.

    :param context: The default template context with user, plugins, etc.
    :type context: DefaultContext
    :param alert_templates: Alert templates grouped by service type.
    :type alert_templates: AlertTemplatesDep
    :param pmm_present_names: Set of template names present in PMM, or ``None``
        when PMM is unreachable.
    :type pmm_present_names: PMMPresentNamesDep
    :param recent_backups: The most recent alert backups for the sidebar widget.
    :type recent_backups: RecentBackupsDep
    :return: The updated context dictionary with alerts data.
    :rtype: dict[str, Any]
    """
    all_templates = [t for templates in alert_templates.values() for t in templates]
    context.update(
        {
            "alert_templates": alert_templates,
            "all_templates": all_templates,
            "service_types": list(ServiceType),
            "pmm_present_names": pmm_present_names,
            "recent_backups": recent_backups,
        }
    )
    return context


AlertsIndexContext = Annotated[dict[str, Any], Depends(get_alerts_index_context)]


async def restore_from_backup(
    pmm_api: PMMRemoteAPI, backup: AlertBackup
) -> dict[str, Any]:
    """Restore alert configuration from a backup snapshot.

    Delete existing alert rules, then recreate templates, rules, contact
    points, and notification policies from the backup data.

    :param pmm_api: The PMM API client for making alerting API calls.
    :type pmm_api: PMMRemoteAPI
    :param backup: The backup record containing the configuration snapshot.
    :type backup: AlertBackup
    :return: A dictionary summarizing the restore operation counts per
        resource type.
    :rtype: dict[str, Any]
    """
    data = backup.data
    results = {}

    existing_rules = await pmm_api.list_rules()
    deleted = 0
    for rule in existing_rules:
        await pmm_api.delete_rule(rule.uid)
        deleted += 1
    results["rules_deleted"] = deleted

    created_templates = 0
    skipped_templates = 0
    for t_data in data.get("templates", []):
        if await pmm_api.template_exists(t_data["name"]):
            skipped_templates += 1
        else:
            await pmm_api.create_template(t_data["template"])
            created_templates += 1
    results["templates"] = {"created": created_templates, "skipped": skipped_templates}

    created_rules = 0
    for r_data in data.get("rules", []):
        await pmm_api.create_rule(
            name=r_data["title"],
            template_name=r_data.get("labels", {}).get(
                "template_name", r_data["title"]
            ),
            folder_uid=r_data.get("folder_uid", ""),
            for_duration=r_data.get("for", "5m"),
            group=r_data.get("group", "SEP Alerts"),
        )
        created_rules += 1
    results["rules_created"] = created_rules

    existing_cps = await pmm_api.list_contact_points()
    existing_cp_map = {cp.name: cp for cp in existing_cps}
    cp_created = 0
    cp_updated = 0
    for cp_data in data.get("contact_points", []):
        if cp_data["name"] in existing_cp_map:
            existing = existing_cp_map[cp_data["name"]]
            await pmm_api.update_contact_point(
                existing.uid,
                cp_data["name"],
                cp_data["type"],
                cp_data.get("settings", {}),
            )
            cp_updated += 1
        else:
            await pmm_api.create_contact_point(
                cp_data["name"],
                cp_data["type"],
                cp_data.get("settings", {}),
            )
            cp_created += 1
    results["contact_points"] = {"created": cp_created, "updated": cp_updated}

    policy_data = data.get("notification_policies", {})
    if policy_data:
        policy = NotificationPolicy.model_validate(policy_data)
        await pmm_api.update_notification_policy(policy)
        results["notification_policies"] = "restored"
    else:
        results["notification_policies"] = "skipped"

    return results
