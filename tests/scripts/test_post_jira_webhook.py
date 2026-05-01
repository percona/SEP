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

"""Tests for the ``scripts/post_jira_webhook.py`` helper."""

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "post_jira_webhook.py"

_spec = importlib.util.spec_from_file_location("post_jira_webhook", _SCRIPT_PATH)
assert _spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
post_jira_webhook = importlib.util.module_from_spec(_spec)
sys.modules["post_jira_webhook"] = post_jira_webhook
_spec.loader.exec_module(post_jira_webhook)


WEBHOOK_URL = "https://api-private.atlassian.com/automation/webhooks/jira/a/abc/xyz"
WEBHOOK_SECRET = "super-secret-token-123"
URL_ENV = "JIRA_VERSION_CREATE_WEBHOOK_URL"
AUTH_ENV = "JIRA_VERSION_CREATE_WEBHOOK_SECRET"
ARGPARSE_ERROR_EXIT_CODE = 2


@pytest.fixture
def webhook_env(monkeypatch):
    """Set both webhook env vars to known values."""
    monkeypatch.setenv(URL_ENV, WEBHOOK_URL)
    monkeypatch.setenv(AUTH_ENV, WEBHOOK_SECRET)


def _fake_ok_response():
    """Return a fake urlopen response object that context-manages cleanly."""

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b""

        def close(self):
            pass

    return FakeResponse()


def _http_error(code):
    """Build a ``urllib.error.HTTPError`` with the given status code."""
    return urllib.error.HTTPError(
        url=WEBHOOK_URL,
        code=code,
        msg=f"HTTP {code}",
        hdrs=None,
        fp=None,
    )


def test_post_webhook_success(monkeypatch, webhook_env):
    """``post_webhook`` exits 0 when ``urlopen`` completes normally."""
    monkeypatch.setattr(
        post_jira_webhook.urllib.request,
        "urlopen",
        lambda *_a, **_kw: _fake_ok_response(),
    )
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 0


def test_post_webhook_2xx_range(monkeypatch, webhook_env):
    """``post_webhook`` treats any non-raising response as success."""

    class NoContent:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b""

    monkeypatch.setattr(
        post_jira_webhook.urllib.request,
        "urlopen",
        lambda *_a, **_kw: NoContent(),
    )
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 0


def test_post_webhook_4xx_returns_failure(monkeypatch, webhook_env, capsys):
    """``post_webhook`` exits 1 and logs the status on HTTP 404."""

    def raise_http(request, timeout):
        raise _http_error(404)

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", raise_http)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    err = capsys.readouterr().err
    assert "HTTP 404" in err
    assert WEBHOOK_SECRET not in err


def test_post_webhook_5xx_returns_failure(monkeypatch, webhook_env, capsys):
    """``post_webhook`` exits 1 on HTTP 500."""

    def raise_http(request, timeout):
        raise _http_error(500)

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", raise_http)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    assert "HTTP 500" in capsys.readouterr().err


def test_post_webhook_network_error_returns_failure(monkeypatch, webhook_env, capsys):
    """``post_webhook`` exits 1 and names the error on ``URLError``."""

    def raise_url_error(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", raise_url_error)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    assert "URLError" in capsys.readouterr().err


def test_post_webhook_timeout_returns_failure(monkeypatch, webhook_env, capsys):
    """``post_webhook`` exits 1 on ``TimeoutError``."""

    def raise_timeout(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", raise_timeout)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    assert "TimeoutError" in capsys.readouterr().err


def test_post_webhook_malformed_url_returns_failure(monkeypatch, webhook_env, capsys):
    """``post_webhook`` exits 1 when ``urlopen`` raises ``ValueError``."""

    def raise_value_error(request, timeout):
        raise ValueError("unknown url type")

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", raise_value_error)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    assert "ValueError" in capsys.readouterr().err


def test_post_webhook_missing_url_env_var(monkeypatch):
    """``post_webhook`` exits 1 and skips the call when URL is unset."""
    monkeypatch.delenv(URL_ENV, raising=False)
    monkeypatch.setenv(AUTH_ENV, WEBHOOK_SECRET)
    calls = []

    def spy(request, timeout):
        calls.append(request)
        return _fake_ok_response()

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", spy)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    assert calls == []


def test_post_webhook_missing_secret_env_var(monkeypatch):
    """``post_webhook`` exits 1 and skips the call when SECRET is unset."""
    monkeypatch.setenv(URL_ENV, WEBHOOK_URL)
    monkeypatch.delenv(AUTH_ENV, raising=False)
    calls = []

    def spy(request, timeout):
        calls.append(request)
        return _fake_ok_response()

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", spy)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    assert calls == []


def test_post_webhook_both_env_vars_missing(monkeypatch):
    """``post_webhook`` exits 1 when both env vars are unset."""
    monkeypatch.delenv(URL_ENV, raising=False)
    monkeypatch.delenv(AUTH_ENV, raising=False)
    calls = []

    def spy(request, timeout):
        calls.append(request)
        return _fake_ok_response()

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", spy)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    assert calls == []


def test_post_webhook_empty_url_env_var(monkeypatch):
    """``post_webhook`` exits 1 when the URL env var is set to empty."""
    monkeypatch.setenv(URL_ENV, "")
    monkeypatch.setenv(AUTH_ENV, WEBHOOK_SECRET)
    calls = []

    def spy(request, timeout):
        calls.append(request)
        return _fake_ok_response()

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", spy)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    assert calls == []


def test_post_webhook_sends_correct_payload_and_headers(monkeypatch, webhook_env):
    """``post_webhook`` POSTs the nested ``data.versionName`` payload with headers."""
    captured = {}

    def capture(request, timeout):
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["method"] = request.get_method()
        captured["content_type"] = request.get_header("Content-type")
        captured["token"] = request.get_header("X-automation-webhook-token")
        captured["timeout"] = timeout
        return _fake_ok_response()

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", capture)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 0
    assert captured["url"] == WEBHOOK_URL
    assert captured["method"] == "POST"
    assert captured["content_type"] == "application/json"
    assert captured["token"] == WEBHOOK_SECRET
    assert captured["timeout"] == post_jira_webhook.WEBHOOK_TIMEOUT_SECONDS
    assert json.loads(captured["data"]) == {"data": {"versionName": "v0.12.0"}}


def test_post_webhook_does_not_log_secret(monkeypatch, webhook_env, capsys):
    """``post_webhook`` never writes the secret value to stderr."""

    def raise_http(request, timeout):
        raise _http_error(401)

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", raise_http)
    post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0")
    assert WEBHOOK_SECRET not in capsys.readouterr().err


def test_post_webhook_does_not_log_url(monkeypatch, webhook_env, capsys):
    """``post_webhook`` never writes the full webhook URL to stderr."""

    def raise_http(request, timeout):
        raise _http_error(401)

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", raise_http)
    post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0")
    assert WEBHOOK_URL not in capsys.readouterr().err


def test_post_webhook_rejects_non_https_scheme(monkeypatch, capsys):
    """``post_webhook`` refuses to POST to an ``http://`` URL."""
    http_url = "http://example.com/webhook"
    monkeypatch.setenv(URL_ENV, http_url)
    monkeypatch.setenv(AUTH_ENV, WEBHOOK_SECRET)
    calls = []

    def spy(request, timeout):
        calls.append(request)
        return _fake_ok_response()

    monkeypatch.setattr(post_jira_webhook.urllib.request, "urlopen", spy)
    assert post_jira_webhook.post_webhook(URL_ENV, AUTH_ENV, "v0.12.0") == 1
    assert calls == []
    err = capsys.readouterr().err
    assert URL_ENV in err
    assert "https" in err
    assert http_url not in err
    assert WEBHOOK_SECRET not in err


def test_main_dispatches_to_post_webhook(monkeypatch, webhook_env):
    """``main`` parses the three required flags and forwards to ``post_webhook``."""
    monkeypatch.setattr(
        post_jira_webhook.urllib.request,
        "urlopen",
        lambda *_a, **_kw: _fake_ok_response(),
    )
    assert (
        post_jira_webhook.main(
            [
                "--url-env",
                URL_ENV,
                "--auth-env",
                AUTH_ENV,
                "--version-tag",
                "v0.12.0",
            ],
        )
        == 0
    )


def test_main_requires_all_flags(capsys):
    """``main`` exits with argparse error when a required flag is missing."""
    with pytest.raises(SystemExit) as exc_info:
        post_jira_webhook.main(["--url-env", URL_ENV])
    assert exc_info.value.code == ARGPARSE_ERROR_EXIT_CODE
    assert "--auth-env" in capsys.readouterr().err
