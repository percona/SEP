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

"""Stage rendered report PDFs on shared disk keyed by Celery job id.

The Celery worker renders a report PDF and writes it here; the web process
serves it from the same shared directory. Only lightweight job metadata
transits the Celery result backend (Redis), so multi-MB PDF blobs never inflate
it. Staged artifacts are reaped by :func:`purge_expired`, driven by the
``purge_report_artifacts`` periodic task.
"""

import logging
import re
import time
import uuid
from pathlib import Path

from app.sep.config import sep_settings

logger = logging.getLogger(__name__)

_ARTIFACT_SUFFIX = ".pdf"
_JOB_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def artifact_dir() -> Path:
    """Return the configured artifact staging directory.

    :return: Absolute path to the staging directory.
    :rtype: Path
    """
    return Path(sep_settings.HEALTH_REPORT.artifact_dir)


def _validate_job_id(job_id: str) -> str:
    """Reject job ids that could escape the staging directory.

    Celery ids are UUIDs, but the download route accepts the id from the URL, so
    the value is treated as untrusted and constrained to a safe charset with no
    path separators.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: The validated job id.
    :rtype: str
    :raises ValueError: If the job id contains unsafe characters.
    """
    if not _JOB_ID_RE.match(job_id):
        raise ValueError(f"Unsafe report artifact job id: {job_id!r}")
    return job_id


def artifact_path(job_id: str) -> Path:
    """Return the on-disk path for a job's PDF artifact.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: Path to the artifact file (may not exist yet).
    :rtype: Path
    :raises ValueError: If the job id is unsafe.
    """
    return artifact_dir() / f"{_validate_job_id(job_id)}{_ARTIFACT_SUFFIX}"


def write_artifact(job_id: str, pdf_bytes: bytes) -> Path:
    """Atomically stage a rendered PDF for later download.

    Writes to a unique temp file in the staging directory and renames it into
    place so a concurrent reader never observes a partial file.

    :param job_id: Celery task identifier.
    :type job_id: str
    :param pdf_bytes: Rendered PDF payload.
    :type pdf_bytes: bytes
    :return: Path to the staged artifact.
    :rtype: Path
    :raises ValueError: If the job id is unsafe.
    """
    path = artifact_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(pdf_bytes)
    tmp.replace(path)
    return path


def read_artifact(job_id: str) -> bytes | None:
    """Return the staged PDF bytes for a job, or ``None`` if absent/expired.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: Artifact bytes, or ``None`` when the file is missing.
    :rtype: bytes | None
    :raises ValueError: If the job id is unsafe.
    """
    path = artifact_path(job_id)
    if path.is_file():
        return path.read_bytes()
    return None


def artifact_exists(job_id: str) -> bool:
    """Return whether a staged PDF artifact exists for a job.

    :param job_id: Celery task identifier.
    :type job_id: str
    :return: ``True`` when the artifact file is present.
    :rtype: bool
    :raises ValueError: If the job id is unsafe.
    """
    return artifact_path(job_id).is_file()


def purge_expired(ttl_seconds: int) -> int:
    """Delete staged artifacts whose mtime is older than ``ttl_seconds``.

    mtime-based reaping (rather than delete-on-download) covers abandoned
    downloads, failed jobs, and worker crashes with a single mechanism, and
    keeps re-downloads working within the retention window.

    :param ttl_seconds: Maximum artifact age in seconds.
    :type ttl_seconds: int
    :return: Number of artifacts removed.
    :rtype: int
    """
    staging = artifact_dir()
    if not staging.is_dir():
        return 0
    cutoff = time.time() - ttl_seconds
    removed = 0
    for path in staging.glob(f"*{_ARTIFACT_SUFFIX}"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            logger.exception("Failed to purge report artifact %s", path)
    return removed
