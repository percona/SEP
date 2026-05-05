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

"""Define the JSON API request and response models for the Snippets plugin.

The shape is snippet-centric: the list endpoint returns snippet entities,
not tasks. Execution is a verb applied to a single snippet
(``POST /{filename}/execute``) and produces a task in the tasks API; the
response surfaces only the resulting task identifier so the FE can navigate
to the task-history view backed by ``app/sep/routes/stream_logs.py``.
"""

__all__ = [
    "BatchApprovalErrorResponse",
    "BatchApprovalResponse",
    "ScriptPreviewResponse",
    "SnippetBatchApproveRequest",
    "SnippetExecutionRequest",
    "SnippetExecutionResponse",
    "SnippetResponse",
]

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.utils.fields import NonEmptyStr, UniqueList


class SnippetResponse(BaseModel):
    """Represent a snippet entity as exposed by the JSON API.

    :param filename: The snippet's filename on disk; doubles as its
        identifier in the API.
    :type filename: NonEmptyStr
    :param title: The display title for the snippet (snippet metadata's
        ``title`` field, falling back to ``filename`` when unset).
    :type title: NonEmptyStr
    :param description: The snippet's free-text description, or an empty
        string when no description is set in metadata.
    :type description: str
    :param size: Snippet file size in bytes.
    :type size: int
    :param md5_digest: 32-character MD5 hex digest of the snippet file.
    :type md5_digest: str
    :param is_approved: Whether the snippet has been approved for execution.
    :type is_approved: bool
    :param approved_at: When the snippet was last approved, or ``None`` if
        unapproved.
    :type approved_at: datetime | None
    :param updated_by: User id that last toggled the approval state, or
        ``None`` if no toggle has occurred.
    :type updated_by: str | None
    :param reason: Free-form reason recorded the last time the snippet's
        approval state changed.
    :type reason: str
    :param requires_sudo: Whether the snippet requires sudo for execution
        (either always-sudo or sudo is user-toggleable).
    :type requires_sudo: bool
    :param sudo_optional: Whether the user can toggle sudo at execution
        time.
    :type sudo_optional: bool
    :param sudo_default: Default value for the sudo toggle when
        ``sudo_optional`` is ``True``.
    :type sudo_default: bool
    :param interpreter: The shell/interpreter command used to execute the
        snippet (for example, ``"bash"`` or ``"python3"``); ``None`` when
        no interpreter mapping resolves.
    :type interpreter: str | None
    :param created_at: When the snippet row was first inserted.
    :type created_at: datetime
    :param updated_at: When the snippet row was last updated, or ``None``
        if never updated since insert.
    :type updated_at: datetime | None
    """

    filename: NonEmptyStr
    title: NonEmptyStr
    description: str
    size: int
    md5_digest: str
    is_approved: bool
    approved_at: datetime | None = None
    updated_by: str | None = None
    reason: str
    requires_sudo: bool
    sudo_optional: bool
    sudo_default: bool
    interpreter: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class SnippetExecutionRequest(BaseModel):
    """Define the JSON body for ``POST /api/plugins/snippets/{filename}/execute``.

    Per-parameter values defined in the snippet's YAML frontmatter go into
    ``args`` and are validated server-side via the snippet's dynamic
    execution model.

    :param executor_host: The hostname of the executor that will run the
        snippet.
    :type executor_host: NonEmptyStr
    :param sudo: Whether to invoke the snippet with sudo. Ignored unless
        the snippet's sudo option is configured as optional.
    :type sudo: bool
    :param args: Per-parameter arguments keyed by parameter name. Validated
        against the snippet's dynamic execution model.
    :type args: dict[str, Any]
    """

    executor_host: NonEmptyStr
    sudo: bool = False
    args: dict[str, Any] = {}


class SnippetExecutionResponse(BaseModel):
    """Represent the response returned from the execute endpoint.

    :param task_name: The task name the snippet was executed under (varies
        based on the snippet's interpreter and pip requirements).
    :type task_name: NonEmptyStr
    :param task_id: The id of the task-history row created by the tasks
        API, when the upstream response includes one.
    :type task_id: int | None
    :param snippet_filename: The filename of the snippet that was
        executed.
    :type snippet_filename: NonEmptyStr
    """

    task_name: NonEmptyStr
    task_id: int | None = None
    snippet_filename: NonEmptyStr


class ScriptPreviewResponse(BaseModel):
    """Represent the backend response for the script-preview endpoint.

    :param content: The full text content of the snippet file (preamble,
        frontmatter, and body concatenated).
    :type content: str
    :param language: A JS syntax-highlighter language identifier derived
        from the snippet's MIME type (for example, ``"bash"`` or
        ``"plaintext"``).
    :type language: str
    :param is_truncated: Whether the preview was truncated to fit
        within the configured per-file character or line limit.
    :type is_truncated: bool
    """

    content: str
    language: str
    is_truncated: bool


class SnippetBatchApproveRequest(BaseModel):
    """JSON body for ``PATCH /api/plugins/snippets/approvals``.

    Unlike the Form-bound :class:`~app.sep.plugins.snippets.deps.SnippetBatchApproveForm`
    twin this is a plain Pydantic body — no ``Form()`` annotations — so FastAPI
    parses it as JSON.

    :param filenames: Unique, non-empty list of snippet filenames to approve in a
        single atomic operation. Duplicates are silently deduplicated by
        ``UniqueList``.
    :type filenames: UniqueList[NonEmptyStr]
    """

    filenames: UniqueList[NonEmptyStr] = Field(min_length=1)


class BatchApprovalResponse(BaseModel):
    """Successful response for the batch-approve endpoint.

    :param approved: Filenames whose approval state was toggled by this
        request (newly approved as a result of the call).
    :type approved: list[str]
    :param skipped_already_approved: Filenames that were already approved
        when the call started; the request is treated as a soft-skip
        (idempotent).
    :type skipped_already_approved: list[str]
    :param count: Length of ``approved``; convenience for callers.
    :type count: int
    """

    approved: list[str]
    skipped_already_approved: list[str]
    count: int


class BatchApprovalErrorResponse(BaseModel):
    """Hard-error response payload for the batch-approve endpoint (400).

    Returned only when the precheck rejects the whole request — either
    because some filenames have no DB row, or because the underlying
    files have been removed from disk. ``already_approved`` is *not*
    listed here; that is treated as a soft-skip in the success path.

    :param missing_in_db: Filenames the request asked to approve that have
        no matching snippet row.
    :type missing_in_db: list[str]
    :param missing_on_disk: Filenames whose row exists but whose underlying
        file is no longer present.
    :type missing_on_disk: list[str]
    """

    missing_in_db: list[str] = Field(default_factory=list)
    missing_on_disk: list[str] = Field(default_factory=list)
