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
import os
import subprocess
import sys
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
    """Patch ``_run``, ``_invoke_post_jira_webhook``, ``_bump_version``, and build artifacts for cmd_rc."""
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

    monkeypatch.setattr(release, "_invoke_post_jira_webhook", spy_webhook)

    def spy_push_commit(*_a, **kwargs):
        call_order.append(("api_commit", kwargs.get("message")))
        return "fakecommitsha"

    def spy_create_tag(tag, target_sha):
        call_order.append(("api_tag", tag, target_sha))

    monkeypatch.setattr(
        release,
        "_api_branch_head_sha",
        lambda *_a, **_kw: "fakebasesha",
    )
    monkeypatch.setattr(release, "_api_push_signed_commit", spy_push_commit)
    monkeypatch.setattr(release, "_api_create_tag_ref", spy_create_tag)

    def fake_wheel_exists(self):
        return True

    monkeypatch.setattr(release.Path, "exists", fake_wheel_exists)
    monkeypatch.setattr(release.Path, "read_text", lambda _self, **_kw: "")
    return runner, call_order


def test_rc_webhook_success_omits_reminder(monkeypatch, capsys):
    """With RC=1 and a successful webhook, the reminder is omitted."""
    _patch_rc_ok(monkeypatch, rc=1, webhook_result=True)
    assert release.cmd_rc("0.12.0", 1, sign_via_github_api=True) == 0
    out = capsys.readouterr().out
    assert "Create Jira version" not in out


def test_rc_webhook_failure_includes_reminder(monkeypatch, capsys):
    """With RC=1 and a failed webhook, the reminder is present."""
    _patch_rc_ok(monkeypatch, rc=1, webhook_result=False)
    assert release.cmd_rc("0.12.0", 1, sign_via_github_api=True) == 0
    out = capsys.readouterr().out
    assert "Create Jira version 0.12.0" in out


def test_rc_with_rc_gt_1_skips_webhook(monkeypatch, capsys):
    """RC > 1 never calls the webhook nor emits the reminder."""
    calls = []
    _patch_rc_ok(monkeypatch, rc=2, webhook_result=True, webhook_calls=calls)
    assert release.cmd_rc("0.12.0", 2, sign_via_github_api=True) == 0
    out = capsys.readouterr().out
    assert calls == []
    assert "Create Jira version" not in out


def test_rc_with_rc_1_calls_webhook(monkeypatch, capsys):
    """RC=1 calls the webhook exactly once with the create-URL env vars."""
    calls = []
    _patch_rc_ok(monkeypatch, rc=1, webhook_result=True, webhook_calls=calls)
    assert release.cmd_rc("0.12.0", 1, sign_via_github_api=True) == 0
    assert calls == [
        (
            release.WEBHOOK_CREATE_URL_ENV,
            release.WEBHOOK_CREATE_AUTH_ENV,
            "v0.12.0",
        ),
    ]


def test_rc_fires_webhook_after_branch_creation_and_before_build(monkeypatch):
    """RC=1 webhook fires after ``git checkout -b`` and before build/API commit/tag."""
    _, call_order = _patch_rc_ok(monkeypatch, rc=1, webhook_result=True)
    assert release.cmd_rc("0.12.0", 1, sign_via_github_api=True) == 0
    webhook_idx = next(i for i, c in enumerate(call_order) if c[0] == "webhook")
    checkout_idx = next(
        i
        for i, c in enumerate(call_order)
        if c[0] == "run" and c[1][:3] == ("git", "checkout", "-b")
    )
    build_idx = next(
        i
        for i, c in enumerate(call_order)
        if c[0] == "run" and c[1] == ("make", "build")
    )
    api_commit_idx = next(i for i, c in enumerate(call_order) if c[0] == "api_commit")
    api_tag_idx = next(i for i, c in enumerate(call_order) if c[0] == "api_tag")
    assert checkout_idx < webhook_idx < build_idx < api_commit_idx < api_tag_idx


# --- cmd_rc preconditions --------------------------------------------------


def test_rc1_rejects_non_main_branch(monkeypatch, capsys):
    """RC=1 aborts with exit 1 when the current branch is not ``main``."""
    runner = _FakeRunner(_make_rc_preconditions(branch="feature/x"))
    monkeypatch.setattr(release, "_run", runner)
    assert release.cmd_rc("0.12.0", 1, sign_via_github_api=True) == 1
    assert "RC=1 requires being on the main branch" in capsys.readouterr().err


def test_rc_rejects_dirty_working_tree(monkeypatch, capsys):
    """``cmd_rc`` aborts when the working tree has uncommitted changes."""
    responses = _make_rc_preconditions(branch="main")
    responses[("git", "status", "--porcelain")] = " M some_file.py\n"
    runner = _FakeRunner(responses)
    monkeypatch.setattr(release, "_run", runner)
    assert release.cmd_rc("0.12.0", 1, sign_via_github_api=True) == 1
    assert "Working tree is not clean" in capsys.readouterr().err


def test_rc1_rejects_existing_local_branch(monkeypatch, capsys):
    """RC=1 aborts when the target ``release/vX.Y.Z`` branch already exists locally."""
    runner = _FakeRunner(_make_rc_preconditions(branch="main"))
    monkeypatch.setattr(release, "_run", runner)
    monkeypatch.setattr(release, "_local_branch_exists", lambda _branch: True)
    assert release.cmd_rc("0.12.0", 1, sign_via_github_api=True) == 1
    assert "already exists locally" in capsys.readouterr().err


def test_rc_via_git_commits_tags_and_pushes(monkeypatch):
    """``sign_via_github_api=False`` uses local ``git commit``/``tag``/``push``."""
    _, call_order = _patch_rc_ok(monkeypatch, rc=1, webhook_result=True)
    assert release.cmd_rc("0.12.0", 1, sign_via_github_api=False) == 0

    run_cmds = [c[1] for c in call_order if c[0] == "run"]
    assert ("git", "commit", "-am", "Bump version to v0.12.0rc1") in run_cmds
    assert ("git", "tag", "v0.12.0rc1") in run_cmds
    assert (
        "git",
        "push",
        "origin",
        "release/v0.12.0",
        "v0.12.0rc1",
    ) in run_cmds
    assert not any(c[0] == "api_commit" for c in call_order)
    assert not any(c[0] == "api_tag" for c in call_order)


def test_rc_via_github_api_errors_without_gh(monkeypatch, capsys):
    """``--sign-via-github-api`` aborts when the ``gh`` CLI is not installed."""
    runner = _FakeRunner(_make_rc_preconditions(branch="main"))
    monkeypatch.setattr(release, "_run", runner)
    monkeypatch.setattr(release, "_gh_available", lambda: False)
    assert release.cmd_rc("0.12.0", 1, sign_via_github_api=True) == 1
    assert "--sign-via-github-api requires the gh CLI" in capsys.readouterr().err


# --- cmd_stable end-to-end -------------------------------------------------


def _patch_stable_ok(monkeypatch):
    """Patch ``_run``, ``_bump_version`` for cmd_stable."""
    runner = _FakeRunner(_make_stable_preconditions("0.12.0"))
    monkeypatch.setattr(release, "_bump_version", lambda *_a, **_kw: None)
    monkeypatch.setattr(release, "_gh_available", lambda: True)

    call_order = []
    runner_orig_call = runner.__call__

    def ordered_runner(cmd, *, check=True, capture=False):
        call_order.append(("run", tuple(cmd)))
        return runner_orig_call(cmd, check=check, capture=capture)

    monkeypatch.setattr(release, "_run", ordered_runner)

    monkeypatch.setattr(
        release,
        "_api_branch_head_sha",
        lambda *_a, **_kw: "fakebasesha",
    )
    monkeypatch.setattr(
        release,
        "_api_push_signed_commit",
        lambda *_a, **_kw: "fakecommitsha",
    )
    monkeypatch.setattr(release, "_api_create_tag_ref", lambda *_a, **_kw: None)

    monkeypatch.setattr(release.Path, "exists", lambda _self: True)
    monkeypatch.setattr(release.Path, "read_text", lambda _self, **_kw: "")
    return runner, call_order


def test_stable_invokes_make_trigger_jenkins_with_release_webhook_envs(monkeypatch):
    """Stable flow forwards the release-webhook env names to ``make trigger-jenkins``."""
    _, call_order = _patch_stable_ok(monkeypatch)
    assert release.cmd_stable("0.12.0", sign_via_github_api=True) == 0
    run_cmds = [c[1] for c in call_order if c[0] == "run"]
    assert (
        "make",
        "trigger-jenkins",
        "TAG=v0.12.0",
        f"WEBHOOK_URL_ENV={release.WEBHOOK_RELEASE_URL_ENV}",
        f"WEBHOOK_AUTH_ENV={release.WEBHOOK_RELEASE_AUTH_ENV}",
    ) in run_cmds


def test_stable_always_prints_mark_jira_reminder(monkeypatch, capsys):
    """Stable flow always prints the "Mark Jira version" reminder.

    The Jira release webhook fires inside ``make trigger-jenkins`` whose
    success/failure ``cmd_stable`` no longer observes — so the reminder is
    unconditional.
    """
    _patch_stable_ok(monkeypatch)
    assert release.cmd_stable("0.12.0", sign_via_github_api=True) == 0
    assert "Mark Jira version 0.12.0 as released" in capsys.readouterr().out


def test_stable_via_git_commits_tags_and_pushes(monkeypatch):
    """``sign_via_github_api=False`` uses local ``git commit``/``tag``/``push``."""
    _, call_order = _patch_stable_ok(monkeypatch)
    assert release.cmd_stable("0.12.0", sign_via_github_api=False) == 0

    run_cmds = [c[1] for c in call_order if c[0] == "run"]
    assert ("git", "commit", "-am", "Bump version to v0.12.0") in run_cmds
    assert ("git", "tag", "v0.12.0") in run_cmds
    assert ("git", "push", "origin", "release/v0.12.0", "v0.12.0") in run_cmds


def test_stable_via_github_api_errors_without_gh(monkeypatch, capsys):
    """``--sign-via-github-api`` aborts when the ``gh`` CLI is not installed."""
    runner = _FakeRunner(_make_stable_preconditions("0.12.0"))
    monkeypatch.setattr(release, "_run", runner)
    monkeypatch.setattr(release, "_gh_available", lambda: False)
    assert release.cmd_stable("0.12.0", sign_via_github_api=True) == 1
    assert "--sign-via-github-api requires the gh CLI" in capsys.readouterr().err


# --- _create_dev_version_bump_pr GH_TOKEN swap -----------------------------


def _patch_dev_pr_runner(monkeypatch, observed_tokens):
    """Patch ``_run`` to record ``GH_TOKEN`` at the time ``gh pr create`` runs."""
    monkeypatch.setattr(release, "_bump_version", lambda *_a, **_kw: None)
    monkeypatch.setattr(release, "_gh_available", lambda: True)

    def runner(cmd, *, check=True, capture=False):
        if tuple(cmd[:3]) == ("gh", "pr", "create"):
            observed_tokens.append(os.environ.get("GH_TOKEN"))
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(release, "_run", runner)


def test_dev_pr_uses_gh_pr_token_when_set_and_restores_gh_token(monkeypatch):
    """``GH_PR_TOKEN`` overrides ``GH_TOKEN`` for ``gh pr create`` only."""
    monkeypatch.setenv("GH_TOKEN", "pat-token")
    monkeypatch.setenv("GH_PR_TOKEN", "github-token")
    observed = []
    _patch_dev_pr_runner(monkeypatch, observed)

    release._create_dev_version_bump_pr("0.12.0", "v0.12.0")

    assert observed == ["github-token"]
    assert os.environ["GH_TOKEN"] == "pat-token"


def test_dev_pr_keeps_gh_token_when_pr_token_unset(monkeypatch):
    """Without ``GH_PR_TOKEN``, ``GH_TOKEN`` is unchanged for ``gh pr create``."""
    monkeypatch.setenv("GH_TOKEN", "pat-token")
    monkeypatch.delenv("GH_PR_TOKEN", raising=False)
    observed = []
    _patch_dev_pr_runner(monkeypatch, observed)

    release._create_dev_version_bump_pr("0.12.0", "v0.12.0")

    assert observed == ["pat-token"]
    assert os.environ["GH_TOKEN"] == "pat-token"


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


# --- main (CalledProcessError handling) ------------------------------------


def test_main_catches_called_process_error_with_list_cmd(monkeypatch, capsys):
    """``main`` surfaces a failing subprocess as a single concise stderr line."""

    def raise_cpe(version, rc, *, sign_via_github_api):
        raise subprocess.CalledProcessError(returncode=128, cmd=["git", "push"])

    monkeypatch.setattr(release, "cmd_rc", raise_cpe)
    assert release.main(["rc", "--version", "0.12.0", "--rc", "1"]) == 1
    err = capsys.readouterr().err
    assert "release: command failed (exit code 128): git push" in err
    assert "Traceback" not in err


def test_main_catches_called_process_error_with_string_cmd(monkeypatch, capsys):
    """``main`` handles a ``CalledProcessError`` whose ``cmd`` is a plain string."""

    def raise_cpe(version, *, sign_via_github_api):
        raise subprocess.CalledProcessError(returncode=1, cmd="make build")

    monkeypatch.setattr(release, "cmd_stable", raise_cpe)
    assert release.main(["stable", "--version", "0.12.0"]) == 1
    err = capsys.readouterr().err
    assert "release: command failed (exit code 1): make build" in err
    assert "Traceback" not in err
