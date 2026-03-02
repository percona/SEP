"""Define tests for the app.sep.routes.artifacts module."""

from unittest.mock import patch

from starlette.status import (
    HTTP_200_OK,
    HTTP_303_SEE_OTHER,
)

from app.core.security import crypto_timestamp_serializer


def _make_token(payload: dict, salt: str = "artifact-download") -> str:
    return crypto_timestamp_serializer.dumps(payload, salt=salt)


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

        with patch("app.sep.routes.artifacts.snippets_settings.SNIPPETS_DIR", tmp_path):
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

        with patch("app.sep.routes.artifacts.DIPPER_PAYLOADS_DIR", tmp_path):
            response = test_client.get(f"/artifacts/download/{token}")

        assert response.status_code == HTTP_200_OK

    def test_expired_token_causes_redirect(self, test_client, tmp_path):
        """Redirect (via SEP exception handler) when token TTL is exceeded."""
        payload = {
            "type": "snippet",
            "filename": "test_script.sh",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with (
            patch("app.sep.routes.artifacts.ARTIFACT_DOWNLOAD_TTL", 0),
            patch("app.sep.routes.artifacts.snippets_settings.SNIPPETS_DIR", tmp_path),
        ):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_303_SEE_OTHER

    def test_tampered_token_causes_redirect(self, test_client):
        """Redirect (via SEP exception handler) for a token with a tampered signature."""
        response = test_client.get(
            "/artifacts/download/this.is.not.a.valid.token", follow_redirects=False
        )
        assert response.status_code == HTTP_303_SEE_OTHER

    def test_wrong_salt_token_causes_redirect(self, test_client):
        """Redirect for a token signed with the wrong salt."""
        payload = {"type": "snippet", "filename": "test.sh", "md5": "abc"}
        token = _make_token(payload, salt="wrong-salt")
        response = test_client.get(
            f"/artifacts/download/{token}", follow_redirects=False
        )
        assert response.status_code == HTTP_303_SEE_OTHER

    def test_valid_token_nonexistent_file_causes_redirect(self, test_client, tmp_path):
        """Redirect (via SEP exception handler) when token is valid but file does not exist."""
        payload = {
            "type": "snippet",
            "filename": "nonexistent.sh",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch("app.sep.routes.artifacts.snippets_settings.SNIPPETS_DIR", tmp_path):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_303_SEE_OTHER

    def test_path_traversal_in_filename_causes_redirect(self, test_client, tmp_path):
        """Redirect when the token filename contains a path traversal sequence."""
        payload = {
            "type": "snippet",
            "filename": "../../etc/passwd",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch("app.sep.routes.artifacts.snippets_settings.SNIPPETS_DIR", tmp_path):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_303_SEE_OTHER

    def test_invalid_artifact_type_causes_redirect(self, test_client):
        """Redirect for a token with an unsupported artifact type."""
        payload = {"type": "backup", "filename": "backup.tar.gz", "md5": "abc"}
        token = _make_token(payload)
        response = test_client.get(
            f"/artifacts/download/{token}", follow_redirects=False
        )
        assert response.status_code == HTTP_303_SEE_OTHER
