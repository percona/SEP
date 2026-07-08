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

"""Shared backup edit-form backfill helper for the backup task apps.

Lives alongside (not inside) :mod:`app.sep.apps.framework` so the backup apps
(``mysql_backups``, ``backup_pg``) can share this backup-family-specific helper
without importing ``framework.__init__`` and unrelated SQLModel tables into
scope. The framework package stays domain-neutral; the S3 / GSUTIL / RSYNC
upload-key knowledge that this helper carries belongs to the backup family, not
the framework.
"""

from collections.abc import Mapping
from typing import Any


def parse_server_list_config(
    task: Mapping[str, Any],
    server_config: Mapping[str, Any],
    all_servers_config: Mapping[str, Any],
    extra_fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild a backup edit-form dict from a parsed ``SERVER_LIST`` config.

    The reverse of the create path: where :func:`assemble_envelope` writes the
    ``SERVER_LIST`` / ``ALL_SERVERS`` envelope, this reads the first server entry
    and the shared ``ALL_SERVERS`` block back into the flat dict a backup app's
    Jinja edit form is populated from. It owns the parts identical across the
    backup apps -- the common base fields, the S3/GSUTIL/RSYNC upload-target
    extraction keyed off ``server_config["UPLOAD"]``, and the catch-all loop that
    lowercases every remaining ``ALL_SERVERS`` key not already present.

    The caller has already parsed the YAML config -- it needs ``server_config``
    and ``all_servers_config`` to compute its own ``extra_fields`` -- so both are
    passed in rather than re-parsed here. ``extra_fields`` (the app-specific keys
    such as ``port``, ``alias``, or the encryption recipient) is merged before the
    catch-all loop so those explicit values win over any lowered ``ALL_SERVERS``
    fallback.

    :param task: The task data retrieved from the Tasks API; supplies ``name`` and
        the ``target`` hostname.
    :param server_config: The first ``SERVER_LIST`` entry.
    :param all_servers_config: The ``ALL_SERVERS`` block (empty dict when absent).
    :param extra_fields: App-specific result keys, merged ahead of the catch-all
        loop so they take precedence over lowered ``ALL_SERVERS`` fallbacks.
    :return: The flat dict used to repopulate the backup edit form.
    """
    result = {
        "name": task["name"],
        "hostname": task["data"]["meta"]["target"],
        "backup_type": server_config["BACKUP_TYPE"],
        "service_id": None,
        "host": server_config["HOST"],
        **extra_fields,
    }

    upload_providers = {
        provider.upper()
        for provider in server_config.get("UPLOAD", [])
        if isinstance(provider, str)
    }
    if "S3" in upload_providers:
        result["s3_bucket"] = all_servers_config.get("S3_BUCKET")
        result["s3_storage_class"] = all_servers_config.get("S3_STORAGE_CLASS")
        result["skip_s3_safety_check"] = all_servers_config.get(
            "SKIP_S3_SAFETY_CHECK", False
        )
    if "GSUTIL" in upload_providers:
        result["gs_bucket"] = all_servers_config.get("GS_BUCKET")
    if "RSYNC" in upload_providers:
        result["rsync_path"] = all_servers_config.get("RSYNC_PATH")

    for key, value in all_servers_config.items():
        if key.lower() not in result:
            result[key.lower()] = value

    return result
