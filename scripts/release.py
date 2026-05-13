#!/usr/bin/env python3
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

"""Release SEP — cut an RC or promote to stable.

Owns the preconditions, version-bump, tagging, GitHub release, and Jenkins
trigger for ``make release-rc`` and ``make release-stable``. Both Makefile
targets are thin shims that forward ``VERSION`` / ``RC`` to this script.

Subcommands:

- ``rc``: cut release candidate ``vX.Y.ZrcN`` from ``main`` (RC=1) or the
  existing ``release/vX.Y.Z`` branch (RC>1). When RC=1, dispatches the Jira
  ``version-create`` automation webhook (via ``scripts/post_jira_webhook.py``)
  before the long-running build / push steps to lock the
  ``fixVersion=sep-next`` scope early.
- ``stable``: promote ``release/vX.Y.Z`` to stable ``vX.Y.Z`` and create a
  dev-version-bump PR on ``main``. The Jira ``version-released`` automation
  webhook is dispatched from the ``trigger-jenkins`` Makefile rule, gated on
  the same ``JENKINS_*`` env vars that gate the build trigger itself.

All webhook dispatch is best-effort: ``scripts/post_jira_webhook.py`` exits
non-zero on failure with a redacted warning on stderr, and the "Next steps"
output always carries the manual reminder.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PYPROJECT = Path("pyproject.toml")
APP_INIT = Path("app/__init__.py")
WEBHOOK_CREATE_URL_ENV = "JIRA_VERSION_CREATE_WEBHOOK_URL"
WEBHOOK_CREATE_AUTH_ENV = "JIRA_VERSION_CREATE_WEBHOOK_SECRET"
WEBHOOK_RELEASE_URL_ENV = "JIRA_VERSION_RELEASE_WEBHOOK_URL"
WEBHOOK_RELEASE_AUTH_ENV = "JIRA_VERSION_RELEASE_WEBHOOK_SECRET"
POST_JIRA_WEBHOOK_SCRIPT = Path(__file__).resolve().parent / "post_jira_webhook.py"

_VERSION_LINE_RE: re.Pattern[str] = re.compile(r'^version = ".*"$', re.MULTILINE)
_DUNDER_VERSION_LINE_RE: re.Pattern[str] = re.compile(
    r'^__version__ = ".*"$',
    re.MULTILINE,
)


def _run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Invoke a subprocess with sensible defaults.

    :param cmd: The command and its arguments.
    :type cmd: list[str]
    :param check: Raise ``CalledProcessError`` on a non-zero exit when ``True``.
    :type check: bool
    :param capture: Capture stdout/stderr instead of inheriting them.
    :type capture: bool
    :return: The completed process.
    :rtype: subprocess.CompletedProcess[str]
    """
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )


def _current_branch() -> str:
    """Return the current git branch name.

    :return: The branch name.
    :rtype: str
    """
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    return result.stdout.strip()


def _working_tree_clean() -> bool:
    """Return ``True`` when ``git status --porcelain`` is empty.

    :return: ``True`` if the working tree has no uncommitted changes.
    :rtype: bool
    """
    result = _run(["git", "status", "--porcelain"], capture=True)
    return not result.stdout.strip()


def _local_branch_exists(branch: str) -> bool:
    """Return ``True`` when a local branch exists.

    :param branch: The branch name to check.
    :type branch: str
    :return: ``True`` if the local branch exists.
    :rtype: bool
    """
    result = _run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        check=False,
    )
    return result.returncode == 0


def _gh_available() -> bool:
    """Return ``True`` when the ``gh`` CLI is on ``PATH``.

    :return: ``True`` if ``gh`` is available.
    :rtype: bool
    """
    return shutil.which("gh") is not None


def _gh_api(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
) -> dict:
    """Call ``gh api`` and return the parsed JSON response.

    Uses the ``gh`` CLI's built-in auth (``GH_TOKEN`` / ``GITHUB_TOKEN`` env
    or ``gh auth login``) and the ``{owner}``/``{repo}`` placeholders in
    ``path`` are substituted by ``gh`` from the current repository context,
    so callers pass them literally (e.g. ``repos/{owner}/{repo}/git/refs``).

    :param method: HTTP method (``GET``, ``POST``, ``PATCH``).
    :type method: str
    :param path: API path, with ``{owner}``/``{repo}`` placeholders.
    :type path: str
    :param payload: Optional JSON-serializable body (sent on stdin with
        ``--input -``).
    :type payload: dict | None
    :return: Parsed JSON response body, or ``{}`` when the response is empty.
    :rtype: dict
    """
    cmd = ["gh", "api", "--method", method, path]
    input_text = None
    if payload is not None:
        cmd.extend(["--input", "-"])
        input_text = json.dumps(payload)
    result = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
        input=input_text,
    )
    return json.loads(result.stdout) if result.stdout.strip() else {}


def _api_branch_head_sha(branch: str) -> str:
    """Return the head commit SHA for ``branch`` on the remote.

    :param branch: Branch name.
    :type branch: str
    :return: Head commit SHA.
    :rtype: str
    """
    ref = _gh_api("GET", f"repos/{{owner}}/{{repo}}/git/ref/heads/{branch}")
    return ref["object"]["sha"]


def _api_push_signed_commit(
    branch: str,
    *,
    base_sha: str,
    message: str,
    files: dict[str, str],
    create_branch: bool,
) -> str:
    """Create a signed commit via the git-data API and publish it on ``branch``.

    Commits produced via ``POST /repos/{o}/{r}/git/commits`` are auto-signed
    by GitHub's ``web-flow`` GPG key, so a tag ref that subsequently points at
    the returned SHA satisfies the ``required_signatures`` rule on the
    ``refs/tags/v*`` ruleset without requiring any GPG key management in the
    runner.

    :param branch: Target branch name.
    :type branch: str
    :param base_sha: Parent commit SHA for the new commit.
    :type base_sha: str
    :param message: Commit message.
    :type message: str
    :param files: Mapping of repository path → full new file content.
    :type files: dict[str, str]
    :param create_branch: When ``True``, create the branch ref at the new
        commit; otherwise update an existing branch ref.
    :type create_branch: bool
    :return: The new commit SHA.
    :rtype: str
    """
    base_commit = _gh_api(
        "GET",
        f"repos/{{owner}}/{{repo}}/git/commits/{base_sha}",
    )
    tree_entries = [
        {"path": path, "mode": "100644", "type": "blob", "content": content}
        for path, content in files.items()
    ]
    new_tree = _gh_api(
        "POST",
        "repos/{owner}/{repo}/git/trees",
        payload={"base_tree": base_commit["tree"]["sha"], "tree": tree_entries},
    )
    new_commit = _gh_api(
        "POST",
        "repos/{owner}/{repo}/git/commits",
        payload={
            "message": message,
            "tree": new_tree["sha"],
            "parents": [base_sha],
        },
    )
    new_sha = new_commit["sha"]
    if create_branch:
        _gh_api(
            "POST",
            "repos/{owner}/{repo}/git/refs",
            payload={"ref": f"refs/heads/{branch}", "sha": new_sha},
        )
    else:
        _gh_api(
            "PATCH",
            f"repos/{{owner}}/{{repo}}/git/refs/heads/{branch}",
            payload={"sha": new_sha},
        )
    return new_sha


def _api_create_tag_ref(tag: str, target_sha: str) -> None:
    """Create a tag ref pointing at ``target_sha``.

    The target commit was produced by :func:`_api_push_signed_commit` and is
    therefore already signed by GitHub's ``web-flow`` key, satisfying the
    ``required_signatures`` rule on ``refs/tags/v*``.

    :param tag: Tag name (e.g. ``v0.12.0rc1``).
    :type tag: str
    :param target_sha: Commit SHA to tag.
    :type target_sha: str
    """
    _gh_api(
        "POST",
        "repos/{owner}/{repo}/git/refs",
        payload={"ref": f"refs/tags/{tag}", "sha": target_sha},
    )


def _publish_signed_release_commit_and_tag(
    *,
    branch: str,
    base_branch: str,
    tag: str,
    commit_message: str,
    create_branch: bool,
) -> None:
    """Create the bump commit + tag via the API, then sync the local branch.

    Extracts the "API commit + tag + local sync" block shared by
    :func:`cmd_rc` and :func:`cmd_stable`. The commit is signed by GitHub's
    ``web-flow`` key, so the tag pointing at it satisfies the
    ``required_signatures`` rule on ``refs/tags/v*``.

    :param branch: Target branch to publish the bump commit on.
    :type branch: str
    :param base_branch: Branch whose head is the parent of the new commit
        (equals ``branch`` except on RC=1, where it is ``main``).
    :type base_branch: str
    :param tag: Tag name to create (e.g. ``v0.12.0rc1``).
    :type tag: str
    :param commit_message: Commit message for the bump commit.
    :type commit_message: str
    :param create_branch: When ``True``, create ``branch`` on the remote at
        the new commit; otherwise update an existing branch ref.
    :type create_branch: bool
    """
    base_sha = _api_branch_head_sha(base_branch)
    commit_sha = _api_push_signed_commit(
        branch,
        base_sha=base_sha,
        message=commit_message,
        files={
            "pyproject.toml": PYPROJECT.read_text(encoding="utf-8"),
            "app/__init__.py": APP_INIT.read_text(encoding="utf-8"),
        },
        create_branch=create_branch,
    )
    _api_create_tag_ref(tag, commit_sha)

    print("==> Syncing local state...")
    _run(["git", "fetch", "origin", branch, "--tags"])
    _run(["git", "reset", "--hard", f"origin/{branch}"])


def _publish_release_commit_and_tag(
    *,
    branch: str,
    base_branch: str,
    tag: str,
    commit_message: str,
    create_branch: bool,
    via_github_api: bool,
) -> None:
    """Publish the bump commit + tag, dispatching on the signing mode.

    When ``via_github_api`` is ``True``, delegate to
    :func:`_publish_signed_release_commit_and_tag` (commit signed by
    GitHub's ``web-flow`` key, required by the ``refs/tags/v*`` ruleset).
    Otherwise commit, tag, and push via local ``git`` — ``base_branch``
    and ``create_branch`` are unused in that path because the local
    branch already tracks the intended history.

    :param branch: Target branch to publish the bump commit on.
    :type branch: str
    :param base_branch: API-path parent branch (ignored in the git path).
    :type base_branch: str
    :param tag: Tag name to create (e.g. ``v0.12.0rc1``).
    :type tag: str
    :param commit_message: Commit message for the bump commit.
    :type commit_message: str
    :param create_branch: API-path branch-creation flag (ignored in the
        git path).
    :type create_branch: bool
    :param via_github_api: When ``True``, use the GitHub git-data API;
        otherwise use local ``git commit``/``tag``/``push``.
    :type via_github_api: bool
    """
    if via_github_api:
        print("==> Creating signed bump commit + tag via GitHub API...")
        _publish_signed_release_commit_and_tag(
            branch=branch,
            base_branch=base_branch,
            tag=tag,
            commit_message=commit_message,
            create_branch=create_branch,
        )
        return
    print("==> Committing version bump...")
    _run(["git", "commit", "-am", commit_message])
    print(f"==> Tagging {tag}...")
    _run(["git", "tag", tag])
    print("==> Pushing branch and tag...")
    _run(["git", "push", "origin", branch, tag])


def _bump_version(pep440_version: str, tag_version: str) -> None:
    """Rewrite the version string in ``pyproject.toml`` and ``app/__init__.py``.

    :param pep440_version: The PEP 440 version (no ``v`` prefix) for
        ``pyproject.toml`` (e.g. ``0.12.0rc1``).
    :type pep440_version: str
    :param tag_version: The tag-style version (with ``v`` prefix) for
        ``app/__init__.py`` (e.g. ``v0.12.0rc1``).
    :type tag_version: str
    """
    pyproject_text = PYPROJECT.read_text(encoding="utf-8")
    new_pyproject_text = _VERSION_LINE_RE.sub(
        f'version = "{pep440_version}"',
        pyproject_text,
        count=1,
    )
    PYPROJECT.write_text(new_pyproject_text, encoding="utf-8")

    init_text = APP_INIT.read_text(encoding="utf-8")
    new_init_text = _DUNDER_VERSION_LINE_RE.sub(
        f'__version__ = "{tag_version}"',
        init_text,
        count=1,
    )
    APP_INIT.write_text(new_init_text, encoding="utf-8")


def _invoke_post_jira_webhook(url_env: str, auth_env: str, version_tag: str) -> bool:
    """Run ``scripts/post_jira_webhook.py`` and return whether it succeeded.

    Used by ``cmd_rc`` for the version-create webhook. The stable-release
    webhook is dispatched from the ``trigger-jenkins`` Makefile rule instead,
    so it shares the same Jenkins-env gate as the build trigger.

    :param url_env: The environment-variable name holding the webhook URL.
    :type url_env: str
    :param auth_env: The environment-variable name holding the webhook token.
    :type auth_env: str
    :param version_tag: The version-name payload value (e.g. ``v0.12.0``).
    :type version_tag: str
    :return: ``True`` when the helper script exits ``0``, ``False`` otherwise.
    :rtype: bool
    """
    proc = _run(
        [
            sys.executable,
            str(POST_JIRA_WEBHOOK_SCRIPT),
            "--url-env",
            url_env,
            "--auth-env",
            auth_env,
            "--version-tag",
            version_tag,
        ],
        check=False,
    )
    return proc.returncode == 0


def _print_rc_next_steps(
    version: str,
    rc: int,
    *,
    jira_version_created: bool,
) -> None:
    """Print the RC "Next steps" block on stdout.

    :param version: The X.Y.Z release version (no ``v`` prefix).
    :type version: str
    :param rc: The RC number.
    :type rc: int
    :param jira_version_created: When ``True``, omit the "Create Jira version"
        reminder. Also omitted for RC > 1 (the version was created on RC=1).
    :type jira_version_created: bool
    """
    print()
    print("Next steps:")
    step = 1
    if rc == 1 and not jira_version_created:
        print(f"  {step}. Create Jira version {version} (if not already created)")
        step += 1
    print(f"  {step}. Deploy to staging and verify")
    print(f"  {step + 1}. Notify the team")


def _print_stable_next_steps(version: str) -> None:
    """Print the stable "Next steps" block on stdout.

    The "Mark Jira version as released" reminder is always printed: the Jira
    release webhook fires inside the ``trigger-jenkins`` Makefile rule, whose
    success/failure this script no longer observes. Marking an
    already-released version through the Jira UI is a harmless no-op.

    :param version: The X.Y.Z release version (no ``v`` prefix).
    :type version: str
    """
    print()
    print("Next steps:")
    print("  1. Publish release notes")
    print(f"  2. Mark Jira version {version} as released")
    print(
        f"  3. Verify the back-merge: git merge-base --is-ancestor v{version} origin/main"
    )


def cmd_rc(version: str, rc: int, *, sign_via_github_api: bool) -> int:
    """Cut release candidate ``vX.Y.ZrcN``.

    :param version: The X.Y.Z release version (no ``v`` prefix).
    :type version: str
    :param rc: The RC number (positive integer).
    :type rc: int
    :param sign_via_github_api: When ``True``, create the bump commit + tag
        via the GitHub git-data API, producing a ``web-flow``-signed target
        that satisfies the ``refs/tags/v*`` ``required_signatures`` rule.
        Requires the ``gh`` CLI. When ``False`` (the default for local
        runs), commit, tag, and push via local ``git`` — relies on the
        user's own git signing setup.
    :type sign_via_github_api: bool
    :return: Process exit code (``0`` on success).
    :rtype: int
    """
    branch = f"release/v{version}"
    rc_version = f"{version}rc{rc}"
    rc_tag = f"v{rc_version}"

    current = _current_branch()
    if rc == 1 and current != "main":
        print(
            f"Error: RC=1 requires being on the main branch (currently on {current})",
            file=sys.stderr,
        )
        return 1
    if not _working_tree_clean():
        print(
            "Error: Working tree is not clean. Commit or stash changes first.",
            file=sys.stderr,
        )
        return 1
    if sign_via_github_api and not _gh_available():
        print(
            "Error: --sign-via-github-api requires the gh CLI "
            "(https://cli.github.com/). Omit the flag to use local git "
            "commit/tag/push instead.",
            file=sys.stderr,
        )
        return 1

    if rc == 1:
        print("==> Pulling latest main...")
        _run(["git", "pull", "origin", "main"])
        print(f"==> Creating release branch {branch}...")
        if _local_branch_exists(branch):
            print(
                f"Error: Branch {branch} already exists locally. "
                "Delete it first or use RC>1.",
                file=sys.stderr,
            )
            return 1
        _run(["git", "checkout", "-b", branch])
    else:
        print(f"==> Checking out existing release branch {branch}...")
        _run(["git", "checkout", branch])
        _run(["git", "pull", "origin", branch])

    jira_version_created = False
    if rc == 1:
        jira_version_created = _invoke_post_jira_webhook(
            WEBHOOK_CREATE_URL_ENV,
            WEBHOOK_CREATE_AUTH_ENV,
            f"v{version}",
        )

    print(f"==> Bumping version to {rc_version}...")
    _bump_version(rc_version, rc_tag)

    print("==> Building wheel...")
    _run(["make", "build"])
    wheel = Path("dist") / f"sep-{rc_version}-py3-none-any.whl"
    if not wheel.exists():
        print(
            f"Error: Wheel not found at {wheel} after build. Aborting before push.",
            file=sys.stderr,
        )
        return 1

    _publish_release_commit_and_tag(
        branch=branch,
        base_branch="main" if rc == 1 else branch,
        tag=rc_tag,
        commit_message=f"Bump version to {rc_tag}",
        create_branch=(rc == 1),
        via_github_api=sign_via_github_api,
    )

    if _gh_available():
        print("==> Creating GitHub pre-release...")
        _run(
            [
                "gh",
                "release",
                "create",
                rc_tag,
                "--prerelease",
                "--generate-notes",
                "--target",
                branch,
            ],
        )
        _run(["gh", "release", "upload", rc_tag, str(wheel)])
    else:
        print("Note: gh CLI not found, skipping GitHub release creation.")

    print()
    print(f"=== RC {rc_version} released successfully ===")
    print()
    _run(["make", "trigger-jenkins", f"TAG={rc_tag}"])

    if rc == 1:
        # Scope-lock + dev-bump are atomic. Main runs at the next .dev0 for
        # the entire QA window — fixes during QA land on the release branch
        # (no main-first cherry-picks under the back-merge model).
        _create_dev_version_bump_pr(version, f"v{version}")

    _print_rc_next_steps(
        version=version,
        rc=rc,
        jira_version_created=jira_version_created,
    )
    return 0


def _create_dev_version_bump_pr(version: str, stable_tag: str) -> None:
    """Branch from ``origin/main``, bump to the next dev version, push and open a PR.

    When ``GH_PR_TOKEN`` is set in the environment, override ``GH_TOKEN`` with
    its value for the ``gh pr create`` call only. This lets the workflow keep a
    PAT in ``GH_TOKEN`` for tag and release operations while delegating the PR
    creation to a token with ``pull-requests: write`` (typically the workflow's
    own ``GITHUB_TOKEN``).

    :param version: The X.Y.Z stable release version (no ``v`` prefix).
    :type version: str
    :param stable_tag: The stable release tag (with ``v`` prefix) for the PR body.
    :type stable_tag: str
    """
    print("==> Creating dev version bump PR on main...")
    parts = version.split(".")
    dev_version = f"{parts[0]}.{int(parts[1]) + 1}.0.dev0"
    dev_branch = f"bump-dev-version-{dev_version}"
    _run(["git", "fetch", "origin", "main"])
    _run(["git", "checkout", "-b", dev_branch, "origin/main"])
    _bump_version(dev_version, f"v{dev_version}")
    _run(["git", "commit", "-am", f"Bump version to v{dev_version}"])
    _run(["git", "push", "-u", "origin", dev_branch])
    if not _gh_available():
        print(
            f"Note: gh CLI not found. Manually create a PR from {dev_branch} to main.",
        )
        return
    pr_token = os.environ.get("GH_PR_TOKEN")
    saved_gh_token = os.environ.get("GH_TOKEN")
    if pr_token:
        os.environ["GH_TOKEN"] = pr_token
    try:
        _run(
            [
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--title",
                f"Bump dev version to v{dev_version}",
                "--body",
                f"Automated dev version bump after {stable_tag} stable release.",
            ],
        )
    finally:
        if pr_token:
            if saved_gh_token is None:
                os.environ.pop("GH_TOKEN", None)
            else:
                os.environ["GH_TOKEN"] = saved_gh_token


def _back_merge_release_into_main(
    *, version: str, release_branch: str, tag: str
) -> int:
    """Back-merge ``release_branch`` into main and assert the ancestor invariant.

    Sequence:

    1. ``git fetch origin``
    2. ``git checkout main`` (and pull to align with origin/main)
    3. ``git merge --no-ff release_branch`` — expected to conflict on
       ``CHANGELOG.md`` and the version files
    4. Resolve CHANGELOG via ``scripts/changelog.py resolve-backmerge --release X.Y.Z``
    5. Resolve version files by re-checking out main's side (the dev-bumped
       value wins; the release branch's stable version must not overwrite it)
    6. ``git commit`` to finalize the merge
    7. ``git push origin main``
    8. Assert ``git merge-base --is-ancestor vX.Y.Z origin/main`` exits 0

    On step-8 failure, this function returns non-zero **without** deleting the
    release branch, so the operator can inspect / re-attempt before losing
    state.

    :param version: The X.Y.Z release version (no ``v`` prefix).
    :type version: str
    :param release_branch: The release branch (``release/vX.Y.Z``).
    :type release_branch: str
    :param tag: The release tag (``vX.Y.Z``).
    :type tag: str
    :return: ``0`` on success, non-zero if any step or the invariant fails.
    :rtype: int
    """
    print("==> Fetching origin for back-merge...")
    _run(["git", "fetch", "origin"])
    print("==> Checking out main...")
    _run(["git", "checkout", "main"])
    _run(["git", "pull", "origin", "main"])

    print(f"==> Merging {release_branch} into main with --no-ff...")
    # Expect a non-zero exit because of the CHANGELOG / version-file
    # conflict — that's the whole point of this step.
    _run(
        ["git", "merge", "--no-ff", "--no-commit", release_branch],
        check=False,
    )

    print("==> Resolving CHANGELOG.md and changelog.d/ via scripts/changelog.py...")
    resolve_result = _run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "changelog.py"),
            "resolve-backmerge",
            "--release",
            version,
        ],
        check=False,
    )
    if resolve_result.returncode != 0:
        print(
            "error: scripts/changelog.py resolve-backmerge failed; aborting back-merge.",
            file=sys.stderr,
        )
        return 1

    print("==> Resolving version files by keeping main's dev version...")
    _run(["git", "checkout", "--ours", "pyproject.toml", "app/__init__.py"])

    print("==> Staging resolved files...")
    _run(
        [
            "git",
            "add",
            "CHANGELOG.md",
            "changelog.d",
            "pyproject.toml",
            "app/__init__.py",
        ]
    )

    print("==> Finalizing the merge commit...")
    _run(
        [
            "git",
            "commit",
            "--no-edit",
            "-m",
            f"Merge release/v{version} into main (back-merge for {tag})",
        ],
    )

    print("==> Pushing main...")
    _run(["git", "push", "origin", "main"])

    print(
        f"==> Asserting ancestor invariant: {tag} must be an ancestor of origin/main..."
    )
    invariant = _run(
        ["git", "merge-base", "--is-ancestor", tag, "origin/main"],
        check=False,
    )
    if invariant.returncode != 0:
        print(
            f"error: post-back-merge invariant failed — {tag} is NOT an "
            "ancestor of origin/main. Leaving release branch in place for "
            "investigation.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_stable(version: str, *, sign_via_github_api: bool) -> int:
    """Promote ``release/vX.Y.Z`` to stable ``vX.Y.Z``.

    :param version: The X.Y.Z release version (no ``v`` prefix).
    :type version: str
    :param sign_via_github_api: When ``True``, create the bump commit + tag
        via the GitHub git-data API, producing a ``web-flow``-signed target
        that satisfies the ``refs/tags/v*`` ``required_signatures`` rule.
        Requires the ``gh`` CLI. When ``False`` (the default for local
        runs), commit, tag, and push via local ``git`` — relies on the
        user's own git signing setup.
    :type sign_via_github_api: bool
    :return: Process exit code (``0`` on success).
    :rtype: int
    """
    expected_branch = f"release/v{version}"
    tag = f"v{version}"

    current = _current_branch()
    if current != expected_branch:
        print(
            f"Error: Must be on {expected_branch} (currently on {current})",
            file=sys.stderr,
        )
        return 1
    if not _working_tree_clean():
        print(
            "Error: Working tree is not clean. Commit or stash changes first.",
            file=sys.stderr,
        )
        return 1
    if sign_via_github_api and not _gh_available():
        print(
            "Error: --sign-via-github-api requires the gh CLI "
            "(https://cli.github.com/). Omit the flag to use local git "
            "commit/tag/push instead.",
            file=sys.stderr,
        )
        return 1

    print(f"==> Bumping version to {version}...")
    _bump_version(version, tag)

    print("==> Building wheel...")
    _run(["make", "build"])
    wheel = Path("dist") / f"sep-{version}-py3-none-any.whl"
    if not wheel.exists():
        print(
            f"Error: Wheel not found at {wheel} after build. Aborting before push.",
            file=sys.stderr,
        )
        return 1

    _publish_release_commit_and_tag(
        branch=expected_branch,
        base_branch=expected_branch,
        tag=tag,
        commit_message=f"Bump version to {tag}",
        create_branch=False,
        via_github_api=sign_via_github_api,
    )

    if _gh_available():
        print("==> Creating GitHub release...")
        _run(["gh", "release", "create", tag, "--generate-notes"])
        _run(["gh", "release", "upload", tag, str(wheel)])
    else:
        print("Note: gh CLI not found, skipping GitHub release creation.")

    back_merge_rc = _back_merge_release_into_main(
        version=version,
        release_branch=expected_branch,
        tag=tag,
    )
    if back_merge_rc != 0:
        return back_merge_rc

    print("==> Deleting release branch (post back-merge)...")
    _run(["git", "push", "origin", "--delete", expected_branch], check=False)
    _run(["git", "branch", "-D", expected_branch], check=False)

    print()
    print(f"=== Stable {version} released successfully ===")
    print()
    _run(
        [
            "make",
            "trigger-jenkins",
            f"TAG={tag}",
            f"WEBHOOK_URL_ENV={WEBHOOK_RELEASE_URL_ENV}",
            f"WEBHOOK_AUTH_ENV={WEBHOOK_RELEASE_AUTH_ENV}",
        ],
    )

    _print_stable_next_steps(version=version)
    return 0


def _positive_int(raw: str) -> int:
    """Parse ``raw`` as a positive integer for argparse.

    :param raw: The raw CLI argument value.
    :type raw: str
    :return: The parsed positive integer.
    :rtype: int
    :raises argparse.ArgumentTypeError: If ``raw`` is not a positive integer.
    """
    try:
        value = int(raw)
    except ValueError as exc:
        msg = f"expected a positive integer, got {raw!r}"
        raise argparse.ArgumentTypeError(msg) from exc
    if value < 1:
        msg = f"expected a positive integer, got {value}"
        raise argparse.ArgumentTypeError(msg)
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the CLI.

    :return: The top-level parser with ``rc`` and ``stable`` subcommands.
    :rtype: argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="release",
        description="Cut a SEP release candidate or promote to stable.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rc_parser = subparsers.add_parser("rc", help="Cut a release candidate.")
    rc_parser.add_argument("--version", required=True, help="X.Y.Z")
    rc_parser.add_argument(
        "--rc",
        required=True,
        type=_positive_int,
        help="RC number (positive integer).",
    )
    rc_parser.add_argument(
        "--sign-via-github-api",
        action="store_true",
        help=(
            "Create the bump commit and tag via the GitHub git-data API "
            "(signed by web-flow). Requires the gh CLI; intended for CI "
            "runs against repositories that require signed tags."
        ),
    )

    stable_parser = subparsers.add_parser(
        "stable",
        help="Promote the release/vX.Y.Z branch to stable vX.Y.Z.",
    )
    stable_parser.add_argument("--version", required=True, help="X.Y.Z")
    stable_parser.add_argument(
        "--sign-via-github-api",
        action="store_true",
        help=(
            "Create the bump commit and tag via the GitHub git-data API "
            "(signed by web-flow). Requires the gh CLI; intended for CI "
            "runs against repositories that require signed tags."
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the requested subcommand.

    Catch ``CalledProcessError`` so a failing ``git``/``gh``/``make`` call
    surfaces as a single concise release-tool error line instead of a Python
    stack trace.

    :param argv: Optional argv override for testing.
    :type argv: list[str] | None
    :return: Process exit code.
    :rtype: int
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "rc":
            return cmd_rc(
                args.version,
                args.rc,
                sign_via_github_api=args.sign_via_github_api,
            )
        return cmd_stable(
            args.version,
            sign_via_github_api=args.sign_via_github_api,
        )
    except subprocess.CalledProcessError as exc:
        cmd = exc.cmd
        if isinstance(cmd, list | tuple):
            cmd_text = " ".join(str(part) for part in cmd)
        else:
            cmd_text = str(cmd)
        print(
            f"release: command failed (exit code {exc.returncode}): {cmd_text}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
