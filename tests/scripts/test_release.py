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

"""Tests for the ``scripts/release.py`` CLI."""

import importlib.util
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "release.py"

_spec = importlib.util.spec_from_file_location("release", _SCRIPT_PATH)
assert _spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
release = importlib.util.module_from_spec(_spec)
sys.modules["release"] = release
_spec.loader.exec_module(release)


SAMPLE_PYPROJECT = """\
[project]
name = "sep"
version = "0.12.0.dev0"
description = "SEP"
"""

SAMPLE_APP_INIT = '''\
"""SEP package."""

__version__ = "v0.12.0.dev0"
'''

WEBHOOK_URL = "https://api-private.atlassian.com/automation/webhooks/jira/a/abc/xyz"
WEBHOOK_SECRET = "super-secret-token-123"
ARGPARSE_ERROR_EXIT_CODE = 2


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Set up a fresh repo layout in ``tmp_path`` and chdir into it.

    :param tmp_path: pytest's per-test temporary directory.
    :type tmp_path: pathlib.Path
    :param monkeypatch: pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: The temporary repo root.
    :rtype: pathlib.Path
    """
    (tmp_path / "pyproject.toml").write_text(SAMPLE_PYPROJECT, encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text(SAMPLE_APP_INIT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def webhook_env(monkeypatch):
    """Set both create- and release-webhook env vars to known values.

    :param monkeypatch: pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    """
    monkeypatch.setenv(release.WEBHOOK_CREATE_URL_ENV, WEBHOOK_URL)
    monkeypatch.setenv(release.WEBHOOK_CREATE_AUTH_ENV, WEBHOOK_SECRET)
    monkeypatch.setenv(release.WEBHOOK_RELEASE_URL_ENV, WEBHOOK_URL)
    monkeypatch.setenv(release.WEBHOOK_RELEASE_AUTH_ENV, WEBHOOK_SECRET)


@pytest.fixture
def jenkins_env(monkeypatch):
    """Set all three Jenkins env vars to known values.

    :param monkeypatch: pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    """
    monkeypatch.setenv("JENKINS_URL", "https://jenkins.example.com")
    monkeypatch.setenv("JENKINS_USER", "bot")
    monkeypatch.setenv("JENKINS_API_TOKEN", "jenkins-token")


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


# --- _post_webhook ---------------------------------------------------------


def test_post_webhook_success(monkeypatch, webhook_env):
    """``_post_webhook`` returns True when ``urlopen`` completes normally."""
    monkeypatch.setattr(
        release.urllib.request,
        "urlopen",
        lambda *_a, **_kw: _fake_ok_response(),
    )
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is True
    )


def test_post_webhook_2xx_range(monkeypatch, webhook_env):
    """``_post_webhook`` treats any non-raising response as success."""

    class NoContent:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        release.urllib.request,
        "urlopen",
        lambda *_a, **_kw: NoContent(),
    )
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is True
    )


def test_post_webhook_4xx_returns_false(monkeypatch, webhook_env, capsys):
    """``_post_webhook`` returns False and logs the status on HTTP 404."""

    def raise_http(request, timeout):
        raise _http_error(404)

    monkeypatch.setattr(release.urllib.request, "urlopen", raise_http)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is False
    )
    err = capsys.readouterr().err
    assert "HTTP 404" in err
    assert WEBHOOK_SECRET not in err


def test_post_webhook_5xx_returns_false(monkeypatch, webhook_env, capsys):
    """``_post_webhook`` returns False on HTTP 500."""

    def raise_http(request, timeout):
        raise _http_error(500)

    monkeypatch.setattr(release.urllib.request, "urlopen", raise_http)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is False
    )
    assert "HTTP 500" in capsys.readouterr().err


def test_post_webhook_network_error_returns_false(monkeypatch, webhook_env, capsys):
    """``_post_webhook`` returns False and names the error on ``URLError``."""

    def raise_url_error(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(release.urllib.request, "urlopen", raise_url_error)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is False
    )
    assert "URLError" in capsys.readouterr().err


def test_post_webhook_timeout_returns_false(monkeypatch, webhook_env, capsys):
    """``_post_webhook`` returns False on ``TimeoutError``."""

    def raise_timeout(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(release.urllib.request, "urlopen", raise_timeout)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is False
    )
    assert "TimeoutError" in capsys.readouterr().err


def test_post_webhook_malformed_url_returns_false(monkeypatch, capsys):
    """``_post_webhook`` returns False when the URL is malformed (``ValueError``)."""
    monkeypatch.setenv(release.WEBHOOK_CREATE_URL_ENV, "not a valid url at all")
    monkeypatch.setenv(release.WEBHOOK_CREATE_AUTH_ENV, WEBHOOK_SECRET)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is False
    )
    assert "ValueError" in capsys.readouterr().err


def test_post_webhook_missing_url_env_var(monkeypatch):
    """``_post_webhook`` returns False and skips the call when URL is unset."""
    monkeypatch.delenv(release.WEBHOOK_CREATE_URL_ENV, raising=False)
    monkeypatch.setenv(release.WEBHOOK_CREATE_AUTH_ENV, WEBHOOK_SECRET)
    calls = []

    def spy(request, timeout):
        calls.append(request)
        return _fake_ok_response()

    monkeypatch.setattr(release.urllib.request, "urlopen", spy)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is False
    )
    assert calls == []


def test_post_webhook_missing_secret_env_var(monkeypatch):
    """``_post_webhook`` returns False and skips the call when SECRET is unset."""
    monkeypatch.setenv(release.WEBHOOK_CREATE_URL_ENV, WEBHOOK_URL)
    monkeypatch.delenv(release.WEBHOOK_CREATE_AUTH_ENV, raising=False)
    calls = []

    def spy(request, timeout):
        calls.append(request)
        return _fake_ok_response()

    monkeypatch.setattr(release.urllib.request, "urlopen", spy)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is False
    )
    assert calls == []


def test_post_webhook_both_env_vars_missing(monkeypatch):
    """``_post_webhook`` returns False when both env vars are unset."""
    monkeypatch.delenv(release.WEBHOOK_CREATE_URL_ENV, raising=False)
    monkeypatch.delenv(release.WEBHOOK_CREATE_AUTH_ENV, raising=False)
    calls = []

    def spy(request, timeout):
        calls.append(request)
        return _fake_ok_response()

    monkeypatch.setattr(release.urllib.request, "urlopen", spy)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is False
    )
    assert calls == []


def test_post_webhook_empty_url_env_var(monkeypatch):
    """``_post_webhook`` returns False when the URL env var is set to empty."""
    monkeypatch.setenv(release.WEBHOOK_CREATE_URL_ENV, "")
    monkeypatch.setenv(release.WEBHOOK_CREATE_AUTH_ENV, WEBHOOK_SECRET)
    calls = []

    def spy(request, timeout):
        calls.append(request)
        return _fake_ok_response()

    monkeypatch.setattr(release.urllib.request, "urlopen", spy)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is False
    )
    assert calls == []


def test_post_webhook_sends_correct_payload_and_headers(monkeypatch, webhook_env):
    """``_post_webhook`` POSTs the nested ``data.versionName`` payload with headers."""
    captured = {}

    def capture(request, timeout):
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["method"] = request.get_method()
        captured["content_type"] = request.get_header("Content-type")
        captured["token"] = request.get_header("X-automation-webhook-token")
        captured["timeout"] = timeout
        return _fake_ok_response()

    monkeypatch.setattr(release.urllib.request, "urlopen", capture)
    assert (
        release._post_webhook(
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        )
        is True
    )
    assert captured["url"] == WEBHOOK_URL
    assert captured["method"] == "POST"
    assert captured["content_type"] == "application/json"
    assert captured["token"] == WEBHOOK_SECRET
    assert captured["timeout"] == release.WEBHOOK_TIMEOUT_SECONDS
    assert json.loads(captured["data"]) == {"data": {"versionName": "v0.12.0"}}


def test_post_webhook_does_not_log_secret(monkeypatch, webhook_env, capsys):
    """``_post_webhook`` never writes the secret value to stderr."""

    def raise_http(request, timeout):
        raise _http_error(401)

    monkeypatch.setattr(release.urllib.request, "urlopen", raise_http)
    release._post_webhook(
        release.WEBHOOK_CREATE_URL_ENV,
        release.WEBHOOK_CREATE_AUTH_ENV,
        "v0.12.0",
    )
    assert WEBHOOK_SECRET not in capsys.readouterr().err


def test_post_webhook_does_not_log_url(monkeypatch, webhook_env, capsys):
    """``_post_webhook`` never writes the full webhook URL to stderr."""

    def raise_http(request, timeout):
        raise _http_error(401)

    monkeypatch.setattr(release.urllib.request, "urlopen", raise_http)
    release._post_webhook(
        release.WEBHOOK_CREATE_URL_ENV,
        release.WEBHOOK_CREATE_AUTH_ENV,
        "v0.12.0",
    )
    assert WEBHOOK_URL not in capsys.readouterr().err


# --- _bump_version ---------------------------------------------------------


def test_bump_version_rewrites_pyproject_and_init(repo):
    """``_bump_version`` rewrites the version lines in both files."""
    release._bump_version("0.12.0rc1", "v0.12.0rc1")
    pyproject_text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    init_text = (repo / "app" / "__init__.py").read_text(encoding="utf-8")
    assert 'version = "0.12.0rc1"' in pyproject_text
    assert 'version = "0.12.0.dev0"' not in pyproject_text
    assert '__version__ = "v0.12.0rc1"' in init_text
    assert '__version__ = "v0.12.0.dev0"' not in init_text
    # surrounding lines preserved
    assert 'name = "sep"' in pyproject_text
    assert '"""SEP package."""' in init_text


def test_bump_version_handles_dev_suffix(repo):
    """``_bump_version`` correctly writes PEP 440 dev versions."""
    release._bump_version("0.13.0.dev0", "v0.13.0.dev0")
    assert 'version = "0.13.0.dev0"' in (repo / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert '__version__ = "v0.13.0.dev0"' in (repo / "app" / "__init__.py").read_text(
        encoding="utf-8"
    )


# --- _jenkins_configured ---------------------------------------------------


def test_jenkins_configured_true_when_all_set(jenkins_env):
    """``_jenkins_configured`` returns True when all three env vars are set."""
    assert release._jenkins_configured() is True


def test_jenkins_configured_false_when_url_unset(monkeypatch, jenkins_env):
    """``_jenkins_configured`` returns False when ``JENKINS_URL`` is unset."""
    monkeypatch.delenv("JENKINS_URL")
    assert release._jenkins_configured() is False


def test_jenkins_configured_false_when_user_unset(monkeypatch, jenkins_env):
    """``_jenkins_configured`` returns False when ``JENKINS_USER`` is unset."""
    monkeypatch.delenv("JENKINS_USER")
    assert release._jenkins_configured() is False


def test_jenkins_configured_false_when_token_unset(monkeypatch, jenkins_env):
    """``_jenkins_configured`` returns False when ``JENKINS_API_TOKEN`` is unset."""
    monkeypatch.delenv("JENKINS_API_TOKEN")
    assert release._jenkins_configured() is False


def test_jenkins_configured_false_when_all_unset(monkeypatch):
    """``_jenkins_configured`` returns False when every env var is unset."""
    for name in release.JENKINS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    assert release._jenkins_configured() is False


# --- cmd_rc end-to-end -----------------------------------------------------


class _FakeRunner:
    """Record ``_run`` invocations and synthesise ``subprocess.CompletedProcess`` results."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, cmd, *, check=True, capture=False):
        self.calls.append(tuple(cmd))
        key = tuple(cmd)
        stdout = self.responses.get(key, "")
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=stdout,
            stderr="",
        )


def _make_rc_preconditions(*, branch="main"):
    """Return canned responses for RC-flow preconditions (branch + clean tree)."""
    return {
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): f"{branch}\n",
        ("git", "status", "--porcelain"): "",
    }


def _make_stable_preconditions(version):
    """Return canned responses for stable-flow preconditions."""
    return {
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): f"release/v{version}\n",
        ("git", "status", "--porcelain"): "",
    }


def _patch_rc_ok(monkeypatch, *, rc=1, webhook_result=True, webhook_calls=None):
    """Patch ``_run``, ``_post_webhook``, ``_bump_version``, and build artifacts for cmd_rc."""
    branch = "main" if rc == 1 else "release/v0.12.0"
    runner = _FakeRunner(_make_rc_preconditions(branch=branch))
    monkeypatch.setattr(release, "_run", runner)
    monkeypatch.setattr(release, "_bump_version", lambda *_a, **_kw: None)
    monkeypatch.setattr(release, "_local_branch_exists", lambda _branch: False)
    monkeypatch.setattr(release, "_gh_available", lambda: True)

    call_order = []
    runner_orig_call = runner.__call__

    def ordered_runner(cmd, *, check=True, capture=False):
        call_order.append(("run", tuple(cmd)))
        return runner_orig_call(cmd, check=check, capture=capture)

    monkeypatch.setattr(release, "_run", ordered_runner)

    def spy_webhook(url_env, secret_env, version):
        call_order.append(("webhook", url_env, secret_env, version))
        if webhook_calls is not None:
            webhook_calls.append((url_env, secret_env, version))
        return webhook_result

    monkeypatch.setattr(release, "_post_webhook", spy_webhook)

    def fake_wheel_exists(self):
        return True

    monkeypatch.setattr(release.Path, "exists", fake_wheel_exists)
    return runner, call_order


def test_rc_webhook_success_omits_reminder(monkeypatch, capsys):
    """With RC=1 and a successful webhook, the reminder is omitted."""
    _patch_rc_ok(monkeypatch, rc=1, webhook_result=True)
    assert release.cmd_rc("0.12.0", 1) == 0
    out = capsys.readouterr().out
    assert "Create Jira version" not in out


def test_rc_webhook_failure_includes_reminder(monkeypatch, capsys):
    """With RC=1 and a failed webhook, the reminder is present."""
    _patch_rc_ok(monkeypatch, rc=1, webhook_result=False)
    assert release.cmd_rc("0.12.0", 1) == 0
    out = capsys.readouterr().out
    assert "Create Jira version 0.12.0" in out


def test_rc_with_rc_gt_1_skips_webhook(monkeypatch, capsys):
    """RC > 1 never calls the webhook nor emits the reminder."""
    calls = []
    _patch_rc_ok(monkeypatch, rc=2, webhook_result=True, webhook_calls=calls)
    assert release.cmd_rc("0.12.0", 2) == 0
    out = capsys.readouterr().out
    assert calls == []
    assert "Create Jira version" not in out


def test_rc_with_rc_1_calls_webhook(monkeypatch, capsys):
    """RC=1 calls the webhook exactly once with the create-URL env vars."""
    calls = []
    _patch_rc_ok(monkeypatch, rc=1, webhook_result=True, webhook_calls=calls)
    assert release.cmd_rc("0.12.0", 1) == 0
    assert calls == [
        (
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        ),
    ]


def test_rc_fires_webhook_after_branch_creation_and_before_build(monkeypatch):
    """RC=1 webhook fires after ``git checkout -b`` and before commit/tag/build."""
    _, call_order = _patch_rc_ok(monkeypatch, rc=1, webhook_result=True)
    assert release.cmd_rc("0.12.0", 1) == 0
    webhook_idx = next(i for i, c in enumerate(call_order) if c[0] == "webhook")
    checkout_idx = next(
        i
        for i, c in enumerate(call_order)
        if c[0] == "run" and c[1][:3] == ("git", "checkout", "-b")
    )
    commit_idx = next(
        i
        for i, c in enumerate(call_order)
        if c[0] == "run" and c[1][:2] == ("git", "commit")
    )
    tag_idx = next(
        i
        for i, c in enumerate(call_order)
        if c[0] == "run" and c[1][:2] == ("git", "tag")
    )
    build_idx = next(
        i
        for i, c in enumerate(call_order)
        if c[0] == "run" and c[1] == ("make", "build")
    )
    assert checkout_idx < webhook_idx < commit_idx < tag_idx < build_idx


# --- cmd_rc preconditions --------------------------------------------------


def test_rc1_rejects_non_main_branch(monkeypatch, capsys):
    """RC=1 aborts with exit 1 when the current branch is not ``main``."""
    runner = _FakeRunner(_make_rc_preconditions(branch="feature/x"))
    monkeypatch.setattr(release, "_run", runner)
    assert release.cmd_rc("0.12.0", 1) == 1
    assert "RC=1 requires being on the main branch" in capsys.readouterr().err


def test_rc_rejects_dirty_working_tree(monkeypatch, capsys):
    """``cmd_rc`` aborts when the working tree has uncommitted changes."""
    responses = _make_rc_preconditions(branch="main")
    responses[("git", "status", "--porcelain")] = " M some_file.py\n"
    runner = _FakeRunner(responses)
    monkeypatch.setattr(release, "_run", runner)
    assert release.cmd_rc("0.12.0", 1) == 1
    assert "Working tree is not clean" in capsys.readouterr().err


def test_rc1_rejects_existing_local_branch(monkeypatch, capsys):
    """RC=1 aborts when the target ``release/vX.Y.Z`` branch already exists locally."""
    runner = _FakeRunner(_make_rc_preconditions(branch="main"))
    monkeypatch.setattr(release, "_run", runner)
    monkeypatch.setattr(release, "_local_branch_exists", lambda _branch: True)
    assert release.cmd_rc("0.12.0", 1) == 1
    assert "already exists locally" in capsys.readouterr().err


# --- cmd_stable end-to-end -------------------------------------------------


def _patch_stable_ok(monkeypatch, *, webhook_result=True, webhook_calls=None):
    """Patch ``_run``, ``_post_webhook``, ``_bump_version`` for cmd_stable."""
    runner = _FakeRunner(_make_stable_preconditions("0.12.0"))
    monkeypatch.setattr(release, "_bump_version", lambda *_a, **_kw: None)
    monkeypatch.setattr(release, "_gh_available", lambda: True)

    call_order = []
    runner_orig_call = runner.__call__

    def ordered_runner(cmd, *, check=True, capture=False):
        call_order.append(("run", tuple(cmd)))
        return runner_orig_call(cmd, check=check, capture=capture)

    monkeypatch.setattr(release, "_run", ordered_runner)

    def spy_webhook(url_env, secret_env, version):
        call_order.append(("webhook", url_env, secret_env, version))
        if webhook_calls is not None:
            webhook_calls.append((url_env, secret_env, version))
        return webhook_result

    monkeypatch.setattr(release, "_post_webhook", spy_webhook)

    monkeypatch.setattr(release.Path, "exists", lambda _self: True)
    return runner, call_order


def test_stable_webhook_success_omits_reminder(monkeypatch, jenkins_env, capsys):
    """With Jenkins configured + webhook success, the reminder is omitted."""
    _patch_stable_ok(monkeypatch, webhook_result=True)
    assert release.cmd_stable("0.12.0") == 0
    out = capsys.readouterr().out
    assert "Mark Jira version" not in out


def test_stable_webhook_failure_includes_reminder(monkeypatch, jenkins_env, capsys):
    """With Jenkins configured + webhook failure, the reminder is present."""
    _patch_stable_ok(monkeypatch, webhook_result=False)
    assert release.cmd_stable("0.12.0") == 0
    out = capsys.readouterr().out
    assert "Mark Jira version 0.12.0 as released" in out


def test_stable_calls_webhook_with_release_env_vars(monkeypatch, jenkins_env):
    """Stable flow calls the webhook exactly once with the release env vars."""
    calls = []
    _patch_stable_ok(monkeypatch, webhook_result=True, webhook_calls=calls)
    assert release.cmd_stable("0.12.0") == 0
    assert calls == [
        (
            release.WEBHOOK_RELEASE_URL_ENV,
            release.WEBHOOK_RELEASE_AUTH_ENV,
            "v0.12.0",
        ),
    ]


def test_stable_skips_webhook_when_jenkins_url_unset(monkeypatch, jenkins_env, capsys):
    """Stable flow skips the webhook when ``JENKINS_URL`` is unset."""
    monkeypatch.delenv("JENKINS_URL")
    calls = []
    _patch_stable_ok(monkeypatch, webhook_result=True, webhook_calls=calls)
    assert release.cmd_stable("0.12.0") == 0
    captured = capsys.readouterr()
    assert calls == []
    assert "Mark Jira version 0.12.0 as released" in captured.out
    assert "JENKINS_*" in captured.err


def test_stable_skips_webhook_when_all_jenkins_env_vars_unset(monkeypatch, capsys):
    """Stable flow skips the webhook when every Jenkins env var is unset."""
    for name in release.JENKINS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    calls = []
    _patch_stable_ok(monkeypatch, webhook_result=True, webhook_calls=calls)
    assert release.cmd_stable("0.12.0") == 0
    captured = capsys.readouterr()
    assert calls == []
    assert "Mark Jira version 0.12.0 as released" in captured.out


# --- argparse --------------------------------------------------------------


def test_argparse_rc_requires_version_and_rc(capsys):
    """The ``rc`` subcommand requires both ``--version`` and ``--rc``."""
    with pytest.raises(SystemExit) as exc_info:
        release.main(["rc", "--version", "0.12.0"])
    assert exc_info.value.code == ARGPARSE_ERROR_EXIT_CODE
    assert "--rc" in capsys.readouterr().err


def test_argparse_stable_requires_version(capsys):
    """The ``stable`` subcommand requires ``--version``."""
    with pytest.raises(SystemExit) as exc_info:
        release.main(["stable"])
    assert exc_info.value.code == ARGPARSE_ERROR_EXIT_CODE
    assert "--version" in capsys.readouterr().err


def test_argparse_rc_rejects_zero(capsys):
    """The ``rc`` subcommand rejects ``--rc 0``."""
    with pytest.raises(SystemExit) as exc_info:
        release.main(["rc", "--version", "0.12.0", "--rc", "0"])
    assert exc_info.value.code == ARGPARSE_ERROR_EXIT_CODE


def test_argparse_rc_rejects_negative(capsys):
    """The ``rc`` subcommand rejects negative ``--rc`` values."""
    with pytest.raises(SystemExit) as exc_info:
        release.main(["rc", "--version", "0.12.0", "--rc", "-1"])
    assert exc_info.value.code == ARGPARSE_ERROR_EXIT_CODE
