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

"""Map MySQL backup-catalog rows onto restore ``backup_source`` Choice options."""

from datetime import UTC

from app.sep.apps.framework.schema import Choice
from app.sep.apps.mysql_backups.models import BackupType, MysqlBackupRun
from app.sep.apps.mysql_backups.restore.models import _validate_backup_source_shell_safe

_TYPE_LABELS = {
    BackupType.MYDUMPER: "Mydumper",
    BackupType.XTRABACKUP: "XtraBackup",
}

_BYTES_PER_KIB = 1024
_SIZE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")
_LABEL_PATH_MAX = 48


def backup_source_value(run: MysqlBackupRun) -> str | None:
    """Return a restore-valid ``backup_source`` location for ``run``, or ``None``.

    Prefers a configured upload destination (``s3://``, ``gs://``, …) when one
    was recorded; otherwise uses the resolved on-disk ``location``. Blank
    strings are treated as unset. Rows with neither cannot become a
    ``Choice`` value (``NonEmptyStr``).

    :param run: A catalogued backup run.
    :return: The preferred location string, or ``None`` when neither field is
        usable.
    """
    for candidate in (run.upload_destination, run.location):
        if candidate is not None and candidate.strip():
            return candidate.strip()
    return None


def _format_size(size_bytes: int | None) -> str:
    """Render a byte count as a short binary unit label.

    :param size_bytes: The size in bytes, or ``None`` when unknown.
    :return: A human-readable size such as ``1.0 GiB``, or ``unknown size``.
    """
    if size_bytes is None:
        return "unknown size"
    size = float(size_bytes)
    unit_index = 0
    while size >= _BYTES_PER_KIB and unit_index < len(_SIZE_UNITS) - 1:
        size /= _BYTES_PER_KIB
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {_SIZE_UNITS[unit_index]}"
    return f"{size:.1f} {_SIZE_UNITS[unit_index]}"


def _elide_path(path: str) -> str:
    """Shorten a long path for the selector label while keeping head and tail.

    :param path: The full backup-source location.
    :return: ``path`` unchanged when short enough, else a middle-elided form.
    """
    if len(path) <= _LABEL_PATH_MAX:
        return path
    keep = (_LABEL_PATH_MAX - 1) // 2
    return f"{path[:keep]}…{path[-keep:]}"


def backup_source_label(run: MysqlBackupRun, *, value: str) -> str:
    """Build a human-readable selector label for a catalogued backup run.

    :param run: A catalogued backup run.
    :param value: The Choice value (restore-valid location) shown in the label.
    :return: A label combining backup type, finish time, size, and location.
    """
    type_label = _TYPE_LABELS.get(run.backup_type, str(run.backup_type))
    if run.finished_at is None:
        finished = "unknown time"
    else:
        finished = run.finished_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"{type_label} · {finished} · {_format_size(run.size_bytes)} · "
        f"{_elide_path(value)}"
    )


def backup_run_to_choice(run: MysqlBackupRun) -> Choice | None:
    """Map one catalog row to a ``Choice``, or ``None`` when it has no usable value.

    Skips locations the restore form's shell-safety validator would reject, so
    the selector never offers a value that 422s on submit.

    :param run: A catalogued backup run.
    :return: A ``Choice`` whose ``value`` is restore-valid, or ``None``.
    """
    value = backup_source_value(run)
    if value is None:
        return None
    try:
        _validate_backup_source_shell_safe(value)
    except ValueError:
        return None
    return Choice(value=value, label=backup_source_label(run, value=value))
