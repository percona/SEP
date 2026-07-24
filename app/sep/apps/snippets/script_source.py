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

"""Back the snippets plugin's JSON surface with the framework ``ScriptSource`` seam.

This adapter is the first real adoption of
:class:`~app.sep.apps.framework.script_source.ScriptSource`: it wires the hooks
``derive_script_routes`` needs around the existing snippets engine
(``app/sep/snippets/``), so :data:`~app.sep.apps.snippets.app.app` can declare
``script_source=`` instead of hand-wiring the listing / per-script schema /
execute / history routes. Being DB-backed, it also opts into the server list-page
capability (``list_query_dep`` + ``list_page``), pushing search/filter/sort/paging
down to SQL instead of fetching every row and slicing in-process.

Three real couplings the synthetic kit deferred are bridged here:

* **The deferred ``-hostname-`` coupling.** ``BaseSnippet.get_execution_model``
  bakes a required ``executor_host`` (validation alias ``-hostname-``) into the
  execution model, but the framework validates ``body.args`` (which never carries
  ``-hostname-``). :class:`SnippetScript.get_execution_model` returns an *args-only*
  subclass that makes ``executor_host`` optional so that validation succeeds; the
  execute hook re-attaches the real host via ``model_construct``.
* **The request-less listing.** ``load_script`` / ``list_scripts`` are plain
  callables with no request or session, so they open their own request-less
  session (mirroring ``app/sep/apps/snippets/celery.py``). Only loaded columns and file/meta
  ``cached_property`` values are read after it closes — never a lazy relationship.
* **The request-less artifact URL.** :func:`build_snippet_source` reads
  ``SNIPPETS_BASE_URL`` / ``BASE_URL`` rather than the legacy request-derived
  fallback, so an unconfigured deployment fails loudly instead of emitting an
  executor-unreachable localhost URL.
"""

from dataclasses import dataclass
from functools import lru_cache

from pydantic import create_model, Field

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.exceptions import (
    HTTPNotFoundException,
    HTTPUnprocessableEntityException,
)
from app.core.pagination import PaginatedResponse, Pagination
from app.sep.apps.framework.schema import AppSchema
from app.sep.apps.framework.script_helpers import build_artifact_download_url
from app.sep.apps.framework.script_source import ScriptExecuteWrite, ScriptSource
from app.sep.apps.snippets.constants import ARTIFACT_TYPE_SNIPPET
from app.sep.apps.snippets.deps import (
    build_snippet_execution_meta,
    get_snippet_list_query,
    validate_snippet_filename,
)
from app.sep.apps.snippets.models import build_snippet_response, SnippetResponse
from app.sep.apps.snippets.schema import (
    build_snippet_schema,
    evaluate_snippet_gates,
    SNIPPETS_PLUGIN_SCHEMA,
)
from app.sep.db import get_async_session_maker
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.list_query import SnippetListQuery
from app.sep.snippets.models.snippet import (
    BaseSnippetArgs,
    EXECUTOR_HOSTS_INPUT_NAME,
    Snippet,
    SnippetExecutionMeta,
)


@lru_cache(maxsize=256)
def _args_only_model(engine_model: type[BaseSnippetArgs]) -> type[BaseSnippetArgs]:
    """Return an args-only twin of a snippet's execution model.

    The framework validates ``body.args``, which never carries the ``-hostname-``
    executor field the engine model requires. The twin redeclares
    ``executor_host`` as optional (``exclude=True`` is inherited, so it still never
    leaks into ``model_dump`` / ``to_args_string``) so ``model_validate`` succeeds
    without it; the execute hook re-attaches the real host afterwards.

    :param engine_model: The snippet's dynamic execution model.
    :return: A subclass whose ``executor_host`` is optional.
    """
    return create_model(
        "SnippetArgsOnly",
        __base__=engine_model,
        executor_host=(
            str | None,
            Field(
                default=None,
                validation_alias=EXECUTOR_HOSTS_INPUT_NAME,
                exclude=True,
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class SnippetScript:
    """Adapt a :class:`Snippet` to the framework's ``ScriptProtocol``.

    Wraps the engine ``Snippet`` and exposes it as ``.snippet`` so the execute
    hook can reuse the engine's executability and meta-assembly logic, while
    ``get_execution_model`` hands the framework the args-only twin.

    :param snippet: The wrapped snippet entity.
    """

    snippet: Snippet

    @property
    def filename(self) -> str:
        """Return the snippet's filename, carried in ``snippet_filename``."""
        return self.snippet.filename

    @property
    def execution_task_name(self) -> str:
        """Return the Tasks-API task name the snippet executes under."""
        return self.snippet.execution_task_name

    def get_execution_model(self) -> type[BaseSnippetArgs]:
        """Return the args-only execution model the framework validates against."""
        return _args_only_model(self.snippet.get_execution_model())


def build_snippet_source(snippet: Snippet) -> str:
    """Return a signed URL for the executor to download the snippet artifact.

    The request-less counterpart of
    :func:`~app.sep.apps.snippets.deps.get_snippet_source`: it reads a
    configured base URL rather than deriving one from the request, since the
    framework's ``build_execution_meta`` hook has no request.

    :param snippet: The snippet to generate the signed download URL for.
    :return: The signed artifact download URL.
    :raises HTTPBadRequestException: When neither ``SNIPPETS_BASE_URL`` nor
        ``BASE_URL`` is configured.
    """
    return build_artifact_download_url(
        None,
        artifact_type=ARTIFACT_TYPE_SNIPPET,
        filename=snippet.filename,
        md5_digest=snippet.md5_digest,
    )


async def _load_script(filename: str) -> SnippetScript:
    """Resolve a snippet filename to a detached :class:`SnippetScript`.

    Opens a request-less session, fetches the row, and expunges it so the script
    stays usable after the session closes (only loaded columns and file/meta
    ``cached_property`` values are read thereafter).

    :param filename: The snippet filename.
    :return: The wrapped, detached snippet.
    :raises HTTPBadRequestException: When the filename is unsafe or malformed
        (the snippets-specific strictness the generic seam guard does not enforce).
    :raises HTTPNotFoundException: When the row is absent or its file is missing.
    """
    validate_snippet_filename(filename)
    async_session = get_async_session_maker()
    async with async_session() as session:
        snippet = await SnippetManager.get_or_404(session, filename=filename)
        if not snippet.path.is_file():
            raise HTTPNotFoundException(detail=f"Snippet {filename!r} not found.")
        session.expunge(snippet)
    return SnippetScript(snippet)


async def _list_scripts() -> list[SnippetScript]:
    """Return every discovered snippet as a detached :class:`SnippetScript`."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        snippets = await SnippetManager.list(session)
        for snippet in snippets:
            session.expunge(snippet)
    return [SnippetScript(snippet) for snippet in snippets]


async def _list_page(
    pagination: Pagination, list_query: SnippetListQuery
) -> PaginatedResponse[SnippetScript]:
    """Return a filtered, sorted, paginated page of snippets from the local DB.

    The SQL search/filter/sort and the filtered total run in
    :meth:`~app.sep.snippets.crud.SnippetManager.list_query_page`; the rows are
    expunged (mirroring :func:`_list_scripts`) so they stay usable after the
    request-less session closes, and wrapped as :class:`SnippetScript` for the
    framework to project through ``list_response``.

    :param pagination: The validated offset/limit window for this page.
    :param list_query: The validated sort/search/filter selections.
    :return: A paginated response over the page's wrapped snippets.
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        page = await SnippetManager.list_query_page(
            session, list_query=list_query, pagination=pagination
        )
        for snippet in page.items:
            session.expunge(snippet)
    return page.map_items(SnippetScript)


def _build_form_schema(script: SnippetScript) -> AppSchema:
    """Build the per-snippet form schema from the snippet's parameters."""
    return build_snippet_schema(script.snippet)


def _list_response(script: SnippetScript) -> SnippetResponse:
    """Project a script into its snippet list-row response."""
    return build_snippet_response(script.snippet)


def _build_execution_meta(
    script: SnippetScript, body: ScriptExecuteWrite
) -> SnippetExecutionMeta:
    """Assemble the execution meta for a snippet, enforcing executability.

    The framework already validated ``body.args`` against the args-only model and
    replaced them with the model's *coerced* dump (keyed by Python attribute name,
    ``executor_host`` excluded), so the full engine model is rebuilt with
    ``model_construct`` — never re-validated, whose alias-keyed fields would reject
    the attribute-keyed dump. When the snippet's sudo option is optional, the user's
    ``ScriptExecuteWrite.sudo`` choice is applied directly: the execution model keys
    sudo on its ``-sudo-`` alias, which the plain ``sudo`` form input never
    satisfies, so honouring the toggle requires setting the attribute by name.

    :param script: The script whose execution meta is being assembled.
    :param body: The validated execute request, ``args`` carrying the coerced dump.
    :return: The execution meta the framework posts to the Tasks API.
    :raises HTTPForbiddenException: When the snippet is unapproved or otherwise
        not executable.
    :raises HTTPUnprocessableEntityException: When a snippet field gate (visibility,
        ``requires`` or ``forbidden``) rejects the submitted args.
    """
    snippet = script.snippet
    if not snippet.can_execute:
        if not snippet.is_approved:
            raise HTTPForbiddenException(
                detail=f"Snippet {snippet.filename!r} is not approved.",
            )
        raise HTTPForbiddenException(
            detail=f"Snippet {snippet.filename!r} cannot be executed.",
        )
    construct_args = dict(body.args)
    if snippet.sudo.is_optional:
        construct_args[BaseSnippetArgs.sudo_field] = body.sudo
    execution_args = snippet.get_execution_model().model_construct(
        executor_host=body.executor_host, **construct_args
    )
    gate_failures = evaluate_snippet_gates(snippet, execution_args)
    if gate_failures:
        raise HTTPUnprocessableEntityException(detail=gate_failures)
    return build_snippet_execution_meta(
        snippet, execution_args, build_snippet_source(snippet)
    )


snippet_source = ScriptSource(
    script_dir=snippets_settings.SNIPPETS_DIR,
    load_script=_load_script,
    list_scripts=_list_scripts,
    build_form_schema=_build_form_schema,
    build_execution_meta=_build_execution_meta,
    list_response=_list_response,
    static_schema=SNIPPETS_PLUGIN_SCHEMA,
    list_response_model=SnippetResponse,
    list_query_dep=get_snippet_list_query,
    list_page=_list_page,
)
