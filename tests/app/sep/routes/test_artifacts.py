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

"""Define tests for the app.sep.routes.artifacts module."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)

from app.core.security import crypto_timestamp_serializer
from app.sep.apps.framework.base import BaseApp
from app.sep.artifact_constants import ARTIFACT_DOWNLOAD_SALT
from app.sep.routes.artifacts import collect_base_dirs


def _make_token(payload: dict, salt: str = ARTIFACT_DOWNLOAD_SALT) -> str:
    return crypto_timestamp_serializer.dumps(payload, salt=salt)


class TestCollectBaseDirs:
    """Cover the registry flatten that builds the artifact base-dir map."""

    def test_raises_on_duplicate_artifact_type(self, mocker) -> None:
        """Raise ``ValueError`` naming a type two apps both declare."""
        first = BaseApp(
            name="first",
            uri_path="/first",
            artifact_base_dirs={"shared": lambda: Path("/tmp/first")},
        )
        second = BaseApp(
            name="second",
            uri_path="/second",
            artifact_base_dirs={"shared": lambda: Path("/tmp/second")},
        )
        mocker.patch(
            "app.sep.routes.artifacts.get_app_registry",
            return_value=[first, second],
        )

        with pytest.raises(ValueError, match="shared"):
            collect_base_dirs()

    def test_flattens_distinct_artifact_types(self, mocker) -> None:
        """Merge distinct per-app declarations into one map."""
        snippet_dir = Path("/tmp/snippets")
        dipper_dir = Path("/tmp/dipper")
        first = BaseApp(
            name="snippets",
            uri_path="/snippets",
            artifact_base_dirs={"snippet": lambda: snippet_dir},
        )
        second = BaseApp(
            name="dipper",
            uri_path="/dipper",
            artifact_base_dirs={"dipper": lambda: dipper_dir},
        )
        mocker.patch(
            "app.sep.routes.artifacts.get_app_registry",
            return_value=[first, second],
        )

        result = collect_base_dirs()

        assert result.keys() == {"snippet", "dipper"}
        assert result["snippet"]() == snippet_dir
        assert result["dipper"]() == dipper_dir


class TestDownloadArtifact:
    """Tests for the GET /artifacts/download/{token} endpoint."""

    def test_valid_snippet_token_existing_file_returns_200(self, test_client, tmp_path):
        """Return 200 and file content for a valid snippet token pointing to an existing file."""
        script_file = tmp_path / "test_script.sh"
        script_file.write_text("#!/bin/bash\necho hello")

        payload = {
            "type": "snippet",
            "filename": "test_script.sh",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch(
            "app.sep.apps.snippets.app.snippets_settings.SNIPPETS_DIR", tmp_path
        ):
            response = test_client.get(f"/artifacts/download/{token}")

        assert response.status_code == HTTP_200_OK

    def test_valid_dipper_token_existing_file_returns_200(self, test_client, tmp_path):
        """Return 200 and file content for a valid dipper token pointing to an existing file."""
        script_file = tmp_path / "collect.sh"
        script_file.write_text("#!/bin/bash\necho dipper")

        payload = {
            "type": "dipper",
            "filename": "collect.sh",
            "md5": "def456",
        }
        token = _make_token(payload)

        with patch("app.sep.apps.dipper.app.DIPPER_PAYLOADS_DIR", tmp_path):
            response = test_client.get(f"/artifacts/download/{token}")

        assert response.status_code == HTTP_200_OK

    def test_expired_token_returns_400(self, test_client, tmp_path):
        """Reject with 400 once the token is older than the configured TTL.

        The signed timestamp is what expires, so the token is minted an hour in
        the past rather than the TTL being set to ``0`` — at ``0`` a
        just-minted token has age ``0``, which is not yet *over* the limit, and
        the request would fall through to the file lookup and 404 instead.
        """
        payload = {
            "type": "snippet",
            "filename": "test_script.sh",
            "md5": "abc123",
        }
        an_hour_ago = time.time() - 3600
        with patch("itsdangerous.timed.time.time", return_value=an_hour_ago):
            token = _make_token(payload)

        with (
            patch("app.sep.routes.artifacts.sep_settings.ARTIFACT_DOWNLOAD_TTL", 60),
            patch("app.sep.apps.snippets.app.snippets_settings.SNIPPETS_DIR", tmp_path),
        ):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_tampered_token_returns_400(self, test_client):
        """Reject with 400 a token whose signature was tampered with."""
        response = test_client.get(
            "/artifacts/download/this.is.not.a.valid.token", follow_redirects=False
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_wrong_salt_token_returns_400(self, test_client):
        """Reject with 400 a token signed with the wrong salt."""
        payload = {"type": "snippet", "filename": "test.sh", "md5": "abc"}
        token = _make_token(payload, salt="wrong-salt")
        response = test_client.get(
            f"/artifacts/download/{token}", follow_redirects=False
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_valid_token_nonexistent_file_returns_404(self, test_client, tmp_path):
        """Return 404 when the token is valid but the file does not exist."""
        payload = {
            "type": "snippet",
            "filename": "nonexistent.sh",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch(
            "app.sep.apps.snippets.app.snippets_settings.SNIPPETS_DIR", tmp_path
        ):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_404_NOT_FOUND

    def test_path_traversal_in_filename_returns_400(self, test_client, tmp_path):
        """Reject with 400 a token whose filename carries a path-traversal sequence."""
        payload = {
            "type": "snippet",
            "filename": "../../etc/passwd",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch(
            "app.sep.apps.snippets.app.snippets_settings.SNIPPETS_DIR", tmp_path
        ):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_invalid_artifact_type_returns_400(self, test_client):
        """Reject with 400 a token naming an unsupported artifact type."""
        payload = {"type": "backup", "filename": "backup.tar.gz", "md5": "abc"}
        token = _make_token(payload)
        response = test_client.get(
            f"/artifacts/download/{token}", follow_redirects=False
        )
        assert response.status_code == HTTP_400_BAD_REQUEST
