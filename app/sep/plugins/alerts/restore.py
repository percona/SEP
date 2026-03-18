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

"""Define the alert restore-from-backup logic."""

from typing import Any

from app.sep.clients.pmm import NotificationPolicy, PMMRemoteAPI
from app.sep.config import sep_settings
from app.sep.plugins.alerts.backup import AlertBackup
from app.sep.plugins.alerts.models import DEFAULT_FOR_DURATION


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
    for rule in existing_rules:
        await pmm_api.delete_rule(rule.uid)
    results["rules_deleted"] = len(existing_rules)

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
            for_duration=r_data.get("for", DEFAULT_FOR_DURATION),
            group=r_data.get("group", sep_settings.PMM.alert_folder_name),
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
