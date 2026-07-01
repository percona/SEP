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

"""Define routes for downloading artifacts via signed URLs."""

from fastapi import APIRouter
from fastapi.responses import FileResponse
from itsdangerous import BadSignature, SignatureExpired

from app.core.exceptions import HTTPBadRequestException, HTTPNotFoundException
from app.core.security import crypto_timestamp_serializer
from app.sep.apps.dipper.constants import DIPPER_PAYLOADS_DIR
from app.sep.artifact_constants import (
    ARTIFACT_DOWNLOAD_SALT,
    ARTIFACT_TYPE_DIPPER,
    ARTIFACT_TYPE_SNIPPET,
)
from app.sep.config import sep_settings
from app.sep.snippets.config import snippets_settings

router = APIRouter(include_in_schema=False)

_BASE_DIRS = {
    ARTIFACT_TYPE_SNIPPET: lambda: snippets_settings.SNIPPETS_DIR,
    ARTIFACT_TYPE_DIPPER: lambda: DIPPER_PAYLOADS_DIR,
}


@router.get("/download/{token}")
async def download_artifact(token: str) -> FileResponse:
    """Serve an artifact file identified by a signed, time-limited token.

    :param token: A signed token encoding the artifact type, filename, and MD5 digest.
    :type token: str
    :return: The artifact file as a streaming response.
    :rtype: FileResponse
    :raises HTTPBadRequestException: If the token is expired, tampered, or references
        an invalid artifact type or a path outside the permitted base directory.
    :raises HTTPNotFoundException: If the resolved file does not exist.
    """
    try:
        payload = crypto_timestamp_serializer.loads(
            token,
            salt=ARTIFACT_DOWNLOAD_SALT,
            max_age=sep_settings.ARTIFACT_DOWNLOAD_TTL,
        )
    except (SignatureExpired, BadSignature) as exc:
        raise HTTPBadRequestException(detail="Invalid or expired token") from exc

    artifact_type = payload.get("type")
    if artifact_type not in _BASE_DIRS:
        raise HTTPBadRequestException(detail="Invalid artifact type")

    if not (filename := payload.get("filename")):
        raise HTTPBadRequestException(detail="Invalid artifact filename")

    base_dir = _BASE_DIRS[artifact_type]().resolve()
    resolved = (base_dir / filename).resolve()
    if not resolved.is_relative_to(base_dir):
        raise HTTPBadRequestException(detail="Invalid artifact path")

    if not resolved.is_file():
        raise HTTPNotFoundException

    return FileResponse(resolved, filename=filename)
