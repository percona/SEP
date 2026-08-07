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

"""Compute and sync ``large-diff`` / ``app-isolated`` labels on a pull request.

``actions/labeler`` matches path globs only; it cannot count changed lines or
express "every file sits in exactly one app slice". This script fills that gap
for the Labels workflow: it reads ``app:<name>`` globs from the base-branch
``.github/labeler.yml``, fetches the PR file list via the GitHub REST API, and
adds or removes the blast-radius labels.

Invoked from ``.github/workflows/labels.yaml`` after a sparse checkout of the
base branch ``.github/`` and ``scripts/`` trees only — never PR-head code.
Uses stdlib ``urllib`` so the workflow step needs no Poetry install.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELER = REPO_ROOT / ".github" / "labeler.yml"
GITHUB_API = "https://api.github.com"
GITHUB_PAGE_SIZE = 100
HTTP_NOT_FOUND = 404

LARGE_DIFF_THRESHOLD = 1500

GENERATED_PREFIXES = (
    "frontend/packages/api/src/generated/",
    "frontend/packages/api/specs/",
)
GENERATED_EXACT = frozenset({"poetry.lock", "frontend/pnpm-lock.yaml"})

_LABEL_KEY = re.compile(r"^([A-Za-z0-9:_-]+):\s*$")
_GLOB_LINE = re.compile(r"^\s*-\s*'([^']+)'\s*$")
_REGEX_ESCAPE = re.compile(r"[.*+?^${}()|[\]\\]")


@dataclass(frozen=True)
class PrFile:
    """Represent one changed file entry from the pulls list-files API."""

    filename: str
    additions: int = 0
    deletions: int = 0


@dataclass(frozen=True)
class BlastRadiusResult:
    """Carry the blast-radius signals derived from a PR file list."""

    changed_lines: int
    large_diff: bool
    app_isolated: bool
    touched_apps: tuple[str, ...]


class GitHubClient(Protocol):
    """Describe the subset of the GitHub REST API used by this script."""

    def list_pr_files(self, owner: str, repo: str, pr_number: int) -> list[PrFile]:
        """Return every changed file for a pull request."""

    def list_issue_labels(self, owner: str, repo: str, issue_number: int) -> set[str]:
        """Return label names currently on an issue or pull request."""

    def add_issue_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> None:
        """Attach one or more labels to an issue or pull request."""

    def remove_issue_label(
        self, owner: str, repo: str, issue_number: int, name: str
    ) -> None:
        """Remove a single label from an issue or pull request."""


def is_generated(filename: str) -> bool:
    """Return whether ``filename`` is excluded from the changed-line count.

    :param filename: Path relative to the repository root.
    :return: ``True`` for lockfiles and generated API client paths.
    """
    if filename in GENERATED_EXACT:
        return True
    return filename.startswith(GENERATED_PREFIXES)


def parse_app_globs(labeler_text: str) -> dict[str, list[str]]:
    """Build a map of ``app:<name>`` label to its path globs.

    :param labeler_text: Full ``.github/labeler.yml`` contents.
    :return: Parsed ``app:<name>`` globs in file order.
    """
    app_globs: dict[str, list[str]] = {}
    current_label: str | None = None

    for line in labeler_text.splitlines():
        key_match = _LABEL_KEY.match(line)
        if key_match:
            label = key_match.group(1)
            current_label = label if label.startswith("app:") else None
            if current_label is not None:
                app_globs[current_label] = []
            continue
        if current_label is None:
            continue
        glob_match = _GLOB_LINE.match(line)
        if glob_match:
            app_globs[current_label].append(glob_match.group(1))

    return app_globs


def match_glob(glob: str, filename: str) -> bool:
    """Return whether ``filename`` matches a labeler path glob.

    :param glob: Labeler path glob from ``labeler.yml``.
    :param filename: Path relative to the repository root.
    :return: ``True`` when the path matches.
    """
    if glob.endswith("/**"):
        return filename.startswith(glob[:-2])
    pattern = "[^/]*".join(
        _REGEX_ESCAPE.sub(r"\\\g<0>", part) for part in glob.split("*")
    )
    return re.fullmatch(pattern, filename) is not None


def app_of(filename: str, app_globs: dict[str, list[str]]) -> str | None:
    """Return the ``app:<name>`` label for ``filename``, if any.

    :param filename: Path relative to the repository root.
    :param app_globs: Parsed labeler app globs.
    :return: The matching label name, or ``None``.
    """
    for label, globs in app_globs.items():
        if any(match_glob(glob, filename) for glob in globs):
            return label
    return None


def compute_blast_radius(
    files: list[PrFile], app_globs: dict[str, list[str]]
) -> BlastRadiusResult:
    """Derive blast-radius labels from a PR file list.

    :param files: Changed files from the pulls list-files API.
    :param app_globs: Parsed ``app:<name>`` globs from ``labeler.yml``.
    :return: Changed-line count and label predicates.
    """
    changed_lines = sum(
        file.additions + file.deletions
        for file in files
        if not is_generated(file.filename)
    )
    large_diff = changed_lines > LARGE_DIFF_THRESHOLD

    touched_apps: set[str] = set()
    has_non_app_file = False
    for file in files:
        app = app_of(file.filename, app_globs)
        if app is None:
            has_non_app_file = True
        else:
            touched_apps.add(app)

    app_isolated = bool(files) and not has_non_app_file and len(touched_apps) == 1
    return BlastRadiusResult(
        changed_lines=changed_lines,
        large_diff=large_diff,
        app_isolated=app_isolated,
        touched_apps=tuple(sorted(touched_apps)),
    )


def sync_blast_radius_labels(
    client: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    result: BlastRadiusResult,
    *,
    log: Callable[[str], None] = print,
) -> None:
    """Add or remove blast-radius labels to match ``result``.

    :param client: GitHub REST client.
    :param owner: Repository owner.
    :param repo: Repository name without owner.
    :param pr_number: Pull request number.
    :param result: Computed blast-radius signals.
    :param log: Callable for informational messages.
    """
    desired = {"large-diff": result.large_diff, "app-isolated": result.app_isolated}
    present = client.list_issue_labels(owner, repo, pr_number)

    for name, want in desired.items():
        if want and name not in present:
            client.add_issue_labels(owner, repo, pr_number, [name])
            log(f"Added {name}")
        elif not want and name in present:
            client.remove_issue_label(owner, repo, pr_number, name)
            log(f"Removed {name}")


class UrllibGitHubClient:
    """Wrap the GitHub REST API using stdlib ``urllib``."""

    def __init__(self, token: str, api_url: str = GITHUB_API) -> None:
        self._api_url = api_url.rstrip("/")
        self._token = token

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | list[str] | None = None,
        tolerate_missing: bool = False,
    ) -> Any:
        url = f"{self._api_url}{path}"
        data = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(  # noqa: S310
            url, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                payload = response.read().decode("utf-8")
                if not payload:
                    return None
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            if tolerate_missing and exc.code == HTTP_NOT_FOUND:
                return None
            raise

    def list_pr_files(self, owner: str, repo: str, pr_number: int) -> list[PrFile]:
        """Return every changed file for a pull request."""
        files: list[PrFile] = []
        page = 1
        while True:
            query = urllib.parse.urlencode({"per_page": GITHUB_PAGE_SIZE, "page": page})
            path = f"/repos/{owner}/{repo}/pulls/{pr_number}/files?{query}"
            batch = self._request("GET", path)
            if not batch:
                break
            files.extend(
                PrFile(
                    filename=item["filename"],
                    additions=item.get("additions", 0),
                    deletions=item.get("deletions", 0),
                )
                for item in batch
            )
            if len(batch) < GITHUB_PAGE_SIZE:
                break
            page += 1
        return files

    def list_issue_labels(self, owner: str, repo: str, issue_number: int) -> set[str]:
        """Return label names currently on an issue or pull request."""
        labels: set[str] = set()
        page = 1
        while True:
            query = urllib.parse.urlencode({"per_page": GITHUB_PAGE_SIZE, "page": page})
            path = f"/repos/{owner}/{repo}/issues/{issue_number}/labels?{query}"
            batch = self._request("GET", path)
            if not batch:
                break
            labels.update(item["name"] for item in batch)
            if len(batch) < GITHUB_PAGE_SIZE:
                break
            page += 1
        return labels

    def add_issue_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> None:
        """Attach one or more labels to an issue or pull request."""
        path = f"/repos/{owner}/{repo}/issues/{issue_number}/labels"
        self._request("POST", path, body=labels)

    def remove_issue_label(
        self, owner: str, repo: str, issue_number: int, name: str
    ) -> None:
        """Remove a single label from an issue or pull request.

        A ``404`` is tolerated here: the label may already be gone when the
        workflow re-runs on a new push.
        """
        encoded = urllib.parse.quote(name, safe="")
        path = f"/repos/{owner}/{repo}/issues/{issue_number}/labels/{encoded}"
        self._request("DELETE", path, tolerate_missing=True)


def apply_blast_radius_labels(
    client: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    labeler_path: Path,
    *,
    log: Callable[[str], None] = print,
) -> BlastRadiusResult:
    """Fetch PR files, compute blast-radius signals, and sync labels.

    :param client: GitHub REST client.
    :param owner: Repository owner.
    :param repo: Repository name without owner.
    :param pr_number: Pull request number.
    :param labeler_path: Path to the base-branch ``.github/labeler.yml``.
    :param log: Callable for informational messages.
    :return: Computed blast-radius signals.
    """
    files = client.list_pr_files(owner, repo, pr_number)
    labeler_text = labeler_path.read_text(encoding="utf-8")
    app_globs = parse_app_globs(labeler_text)
    result = compute_blast_radius(files, app_globs)
    log(
        f"changedLines={result.changed_lines} largeDiff={result.large_diff} "
        f"appIsolated={result.app_isolated} apps=[{', '.join(result.touched_apps)}]"
    )
    sync_blast_radius_labels(client, owner, repo, pr_number, result, log=log)
    return result


def main(argv: list[str] | None = None) -> int:
    """Compute and sync blast-radius labels for one pull request.

    :param argv: CLI arguments (defaults to ``sys.argv[1:]``).
    :return: ``0`` on success; ``1`` on error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, help="repository owner")
    parser.add_argument("--repo", required=True, help="repository name")
    parser.add_argument(
        "--pr-number", type=int, required=True, help="pull request number"
    )
    parser.add_argument(
        "--labeler",
        type=Path,
        default=DEFAULT_LABELER,
        help="path to .github/labeler.yml (default: repo-root .github/labeler.yml)",
    )
    parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="environment variable holding the GitHub API token (default: GITHUB_TOKEN)",
    )
    args = parser.parse_args(argv)

    token = os.environ.get(args.token_env)
    if not token:
        print(f"{args.token_env} is not set", file=sys.stderr)
        return 1
    if not args.labeler.is_file():
        print(f"{args.labeler}: file not found", file=sys.stderr)
        return 1

    client = UrllibGitHubClient(token)
    try:
        apply_blast_radius_labels(
            client,
            args.owner,
            args.repo,
            args.pr_number,
            args.labeler,
            log=lambda message: print(message, flush=True),
        )
    except urllib.error.URLError as exc:
        print(f"GitHub API request failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
