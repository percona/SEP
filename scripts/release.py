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

Owns the preconditions, version-bump, tagging, GitHub release, Jenkins trigger,
and Jira version webhook dispatch for ``make release-rc`` and
``make release-stable``. Both Makefile targets are thin shims that forward
``VERSION`` / ``RC`` to this script.

Subcommands:

- ``rc``: cut release candidate ``vX.Y.ZrcN`` from ``main`` (RC=1) or the
  existing ``release/vX.Y.Z`` branch (RC>1). When RC=1 and the
  ``JIRA_VERSION_CREATE_WEBHOOK_*`` env vars are set, POSTs to the Jira
  automation webhook before the long-running build / push steps (locks
  ``fixVersion=sep-next`` scope early).
- ``stable``: promote ``release/vX.Y.Z`` to stable ``vX.Y.Z`` and create a
  dev-version-bump PR on ``main``. When the build is actually in flight
  (``JENKINS_*`` env vars set) and the ``JIRA_VERSION_RELEASE_WEBHOOK_*`` env
  vars are set, POSTs to the Jira automation webhook after the release is
  complete.

All webhook dispatch is best-effort: failure logs a redacted warning to stderr
and leaves the corresponding manual-reminder line in the "Next steps" output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PYPROJECT = Path("pyproject.toml")
APP_INIT = Path("app/__init__.py")
WEBHOOK_TIMEOUT_SECONDS = 10
WEBHOOK_CREATE_URL_ENV = "JIRA_VERSION_CREATE_WEBHOOK_URL"
WEBHOOK_CREATE_AUTH_ENV = "JIRA_VERSION_CREATE_WEBHOOK_SECRET"
WEBHOOK_RELEASE_URL_ENV = "JIRA_VERSION_RELEASE_WEBHOOK_URL"
WEBHOOK_RELEASE_AUTH_ENV = "JIRA_VERSION_RELEASE_WEBHOOK_SECRET"
JENKINS_ENV_VARS: tuple[str, ...] = ("JENKINS_URL", "JENKINS_USER", "JENKINS_API_TOKEN")

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


def _post_webhook(url_env: str, auth_env: str, version_tag: str) -> bool:
    """POST the Jira version-name payload to the webhook. Best-effort.

    Catch ``HTTPError`` before the broader transport-error branch because
    ``HTTPError`` is a subclass of ``URLError``; the reverse order would
    swallow the status code needed for the warning and tests.

    :param url_env: The environment-variable name holding the webhook URL.
    :type url_env: str
    :param auth_env: The environment-variable name holding the webhook token.
    :type auth_env: str
    :param version_tag: The version-name payload value (e.g. ``v0.12.0``).
    :type version_tag: str
    :return: ``True`` on HTTP 2xx, ``False`` on any error (missing env var,
        network failure, timeout, or non-2xx response).
    :rtype: bool
    """
    url = os.environ.get(url_env)
    secret = os.environ.get(auth_env)
    if not url or not secret:
        return False
    payload = json.dumps({"data": {"versionName": version_tag}}).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Automation-Webhook-Token": secret,
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS)  # noqa: S310
    except urllib.error.HTTPError as exc:
        print(
            f"warning: Jira webhook returned HTTP {exc.code} ({url_env})",
            file=sys.stderr,
        )
        return False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(
            f"warning: Jira webhook dispatch failed ({url_env}): {type(exc).__name__}",
            file=sys.stderr,
        )
        return False
    return True


def _jenkins_configured() -> bool:
    """Return ``True`` iff all three Jenkins env vars are set.

    Gate the stable-release webhook: if Jenkins is not configured,
    ``make trigger-jenkins`` was a no-op, so rule #17 must not fire — doing so
    would mark the Jira version released and send the stakeholder email before
    any build is in flight.

    :return: ``True`` when every Jenkins env var has a non-empty value.
    :rtype: bool
    """
    return all(os.environ.get(name) for name in JENKINS_ENV_VARS)


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


def _print_stable_next_steps(
    version: str,
    *,
    jira_version_released: bool,
) -> None:
    """Print the stable "Next steps" block on stdout.

    :param version: The X.Y.Z release version (no ``v`` prefix).
    :type version: str
    :param jira_version_released: When ``True``, omit the "Mark Jira version
        as released" reminder.
    :type jira_version_released: bool
    """
    print()
    print("Next steps:")
    step = 1
    print(f"  {step}. Publish release notes")
    step += 1
    if not jira_version_released:
        print(f"  {step}. Mark Jira version {version} as released")
        step += 1
    print(f"  {step}. Merge the dev version bump PR")


def cmd_rc(version: str, rc: int) -> int:
    """Cut release candidate ``vX.Y.ZrcN``.

    :param version: The X.Y.Z release version (no ``v`` prefix).
    :type version: str
    :param rc: The RC number (positive integer).
    :type rc: int
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
        jira_version_created = _post_webhook(
            WEBHOOK_CREATE_URL_ENV,
            WEBHOOK_CREATE_AUTH_ENV,
            f"v{version}",
        )

    print(f"==> Bumping version to {rc_version}...")
    _bump_version(rc_version, rc_tag)
    print("==> Committing version bump...")
    _run(["git", "commit", "-am", f"Bump version to {rc_tag}"])
    print(f"==> Tagging {rc_tag}...")
    _run(["git", "tag", rc_tag])

    print("==> Building wheel...")
    _run(["make", "build"])
    wheel = Path("dist") / f"sep-{rc_version}-py3-none-any.whl"
    if not wheel.exists():
        print(
            f"Error: Wheel not found at {wheel} after build. Aborting before push.",
            file=sys.stderr,
        )
        return 1

    print("==> Pushing branch and tag...")
    _run(["git", "push", "origin", branch, rc_tag])

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

    _print_rc_next_steps(
        version=version,
        rc=rc,
        jira_version_created=jira_version_created,
    )
    return 0


def cmd_stable(version: str) -> int:
    """Promote ``release/vX.Y.Z`` to stable ``vX.Y.Z``.

    :param version: The X.Y.Z release version (no ``v`` prefix).
    :type version: str
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

    print(f"==> Bumping version to {version}...")
    _bump_version(version, tag)
    print("==> Committing version bump...")
    _run(["git", "commit", "-am", f"Bump version to {tag}"])
    print(f"==> Tagging {tag}...")
    _run(["git", "tag", tag])

    print("==> Building wheel...")
    _run(["make", "build"])
    wheel = Path("dist") / f"sep-{version}-py3-none-any.whl"
    if not wheel.exists():
        print(
            f"Error: Wheel not found at {wheel} after build. Aborting before push.",
            file=sys.stderr,
        )
        return 1

    print("==> Pushing branch and tag...")
    _run(["git", "push", "origin", expected_branch, tag])

    if _gh_available():
        print("==> Creating GitHub release...")
        _run(["gh", "release", "create", tag, "--generate-notes"])
        _run(["gh", "release", "upload", tag, str(wheel)])
    else:
        print("Note: gh CLI not found, skipping GitHub release creation.")

    print("==> Creating dev version bump PR on main...")
    parts = version.split(".")
    dev_version = f"{parts[0]}.{int(parts[1]) + 1}.0.dev0"
    dev_branch = f"bump-dev-version-{dev_version}"
    _run(["git", "fetch", "origin", "main"])
    _run(["git", "checkout", "-b", dev_branch, "origin/main"])
    _bump_version(dev_version, f"v{dev_version}")
    _run(["git", "commit", "-am", f"Bump version to v{dev_version}"])
    _run(["git", "push", "-u", "origin", dev_branch])
    if _gh_available():
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
                f"Automated dev version bump after {tag} stable release.",
            ],
        )
    else:
        print(
            f"Note: gh CLI not found. Manually create a PR from {dev_branch} to main.",
        )

    print("==> Deleting release branch...")
    _run(["git", "checkout", "main"])
    _run(["git", "push", "origin", "--delete", expected_branch], check=False)
    _run(["git", "branch", "-d", expected_branch], check=False)

    print()
    print(f"=== Stable {version} released successfully ===")
    print()
    _run(["make", "trigger-jenkins", f"TAG={tag}"])

    jira_version_released = False
    if _jenkins_configured():
        jira_version_released = _post_webhook(
            WEBHOOK_RELEASE_URL_ENV,
            WEBHOOK_RELEASE_AUTH_ENV,
            tag,
        )
    else:
        print(
            "note: JENKINS_* env vars not set, skipping Jira release webhook "
            "(manual 'Mark Jira version as released' reminder retained).",
            file=sys.stderr,
        )

    _print_stable_next_steps(
        version=version,
        jira_version_released=jira_version_released,
    )
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

    stable_parser = subparsers.add_parser(
        "stable",
        help="Promote the release/vX.Y.Z branch to stable vX.Y.Z.",
    )
    stable_parser.add_argument("--version", required=True, help="X.Y.Z")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the requested subcommand.

    :param argv: Optional argv override for testing.
    :type argv: list[str] | None
    :return: Process exit code.
    :rtype: int
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "rc":
        return cmd_rc(args.version, args.rc)
    return cmd_stable(args.version)


if __name__ == "__main__":
    sys.exit(main())
