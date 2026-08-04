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

"""Define the JSON API response models for the Snippets plugin.

The shape is snippet-centric: the list endpoint returns snippet entities,
not tasks. Execution is a verb applied to a single snippet
(``POST /snippet/execute``) and produces a task in the tasks API via the
framework's :class:`~app.sep.apps.framework.script_source.ScriptSource` seam;
the request/response bodies for that route are the framework's
``ScriptExecuteWrite`` / ``ScriptExecutionResponse``.
"""

__all__ = [
    "BatchApprovalErrorResponse",
    "BatchApprovalResponse",
    "RefreshResponse",
    "SnippetBatchApproveRequest",
    "SnippetResponse",
    "SnippetsCapabilitiesResponse",
    "build_snippet_response",
]

from datetime import datetime

from pydantic import BaseModel, computed_field, Field

from app.core.utils.fields import NonEmptyStr, UniqueList
from app.sep.apps.framework.schema import AppDeploymentCapabilities
from app.sep.snippets.config import SnippetSudoOption
from app.sep.snippets.models.snippet import Snippet


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
    :param service_type: The snippet's free-form service type
        (``service_type`` metadata field, for example ``"mysql"`` or
        ``"mongodb"``), or ``None`` when the snippet declares no service
        type. Distinct from the inventory ``ServiceTypeEnum``.
    :type service_type: str | None
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
    service_type: str | None = None
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


def build_snippet_response(snippet: Snippet) -> SnippetResponse:
    """Project a :class:`Snippet` into its API response shape.

    :param snippet: The snippet ORM row to transform.
    :return: The API response model mapped from ``snippet``.
    """
    return SnippetResponse(
        filename=snippet.filename,
        title=snippet.title,
        description=snippet.description,
        service_type=snippet.service_type,
        size=snippet.size,
        md5_digest=snippet.md5_digest,
        is_approved=snippet.is_approved,
        approved_at=snippet.approved_at,
        updated_by=snippet.updated_by,
        reason=snippet.reason,
        requires_sudo=(
            snippet.sudo == SnippetSudoOption.ALWAYS or snippet.sudo.is_optional
        ),
        sudo_optional=snippet.sudo.is_optional,
        sudo_default=snippet.sudo.sudo_default,
        interpreter=snippet.execution_interpreter,
        created_at=snippet.created_at,
        updated_at=snippet.updated_at,
    )


class SnippetBatchApproveRequest(BaseModel):
    """Represent the JSON body for ``PATCH /api/apps/snippets/approvals``.

    Unlike the Form-bound :class:`~app.sep.snippets.deps.SnippetBatchApproveForm`
    twin this is a plain Pydantic body — no ``Form()`` annotations — so FastAPI
    parses it as JSON.

    :param filenames: Unique, non-empty list of snippet filenames to approve in a
        single atomic operation. Duplicates are silently deduplicated by
        ``UniqueList``.
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
    """

    approved: list[str]
    skipped_already_approved: list[str]

    @computed_field
    @property
    def count(self) -> int:
        """Return the number of newly approved snippets.

        :return: Length of ``approved``.
        :rtype: int
        """
        return len(self.approved)


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


class RefreshResponse(BaseModel):
    """Represent the successful result of a manual snippets-refresh operation.

    :param refreshed_at: UTC timestamp at which the refresh completed.
    :type refreshed_at: datetime
    """

    refreshed_at: datetime


class SnippetServiceTypesResponse(BaseModel):
    """Carry the whole-dataset service-type facet for the list filter.

    Sourced across every snippet (not the loaded page) so the list page's
    service-type dropdown can offer every value the dataset contains.

    :param service_types: The sorted distinct non-blank service types.
    :param has_uncategorized: Whether any snippet has an absent or blank service
        type (surfaced as the "Uncategorized" filter option).
    """

    service_types: list[str]
    has_uncategorized: bool


class SnippetsCapabilitiesResponse(AppDeploymentCapabilities):
    """Represent per-deployment capability flags for the Snippets plugin.

    Exposes flags that gate the visibility of admin-only UI affordances
    (currently the manual refresh button) so the React shell can decide
    whether to render those controls without probing the gated endpoints.

    Distinct from :class:`~app.sep.apps.framework.schema.Capabilities`,
    which describes static UI feature flags on
    :attr:`~app.sep.apps.framework.schema.AppSchema.capabilities`
    (chaining, scheduling, alert_on_fail). This model is the per-
    deployment runtime counterpart returned by ``GET /capabilities``.

    :param manual_sync_enabled: Whether manual snippet refresh is enabled
        in this deployment (mirrors ``snippets_settings.ENABLE_MANUAL_SYNC``).
    :type manual_sync_enabled: bool
    """

    manual_sync_enabled: bool
