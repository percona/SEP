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
``derive_script_routes`` needs around the surrounding snippets engine
(``app/sep/snippets/``), so :data:`~app.sep.apps.snippets.app.app` can declare
``script_source=`` instead of hand-wiring the listing / per-script schema /
execute / history routes. Being DB-backed, its ``list_scripts`` hook pushes the
list route's search/sort/filter/paging down to SQL (via
:meth:`~app.sep.snippets.crud.SnippetManager.snippet_list_page` over
:attr:`~app.sep.snippets.crud.SnippetManager.list_query_spec`) instead of fetching
every row and slicing in-process. Its ``list_query_dep`` composes the Core sort/search
dependency with the snippets approval and service-type filters, so the spec stays the
sole sort allowlist while the route keeps its filter surface.

Three real couplings the synthetic kit deferred are bridged here:

* **The deferred ``-hostname-`` coupling.** ``BaseSnippet.get_execution_model``
  bakes a required ``executor_host`` (validation alias ``-hostname-``) into the
  execution model, but the framework validates ``body.args`` (which never carries
  ``-hostname-``). :class:`SnippetScript.get_execution_model` returns an *args-only*
  subclass that makes ``executor_host`` optional so that validation succeeds; the
  execute hook re-attaches the real host via ``model_construct``.
* **The request-less listing.** ``load_script`` / ``list_scripts`` /
  ``load_scripts`` are plain callables with no request or session, so they open
  their own request-less session (mirroring ``app/sep/snippets/celery.py``).
  ``load_scripts`` resolves a whole selection in one ``IN`` query. Only loaded
  columns and file/meta ``cached_property`` values are read after it closes —
  never a lazy relationship.
* **The request-less artifact URL.** :func:`build_snippet_source` reads
  ``SNIPPETS_BASE_URL`` / ``BASE_URL`` rather than the legacy request-derived
  fallback, so an unconfigured deployment fails loudly instead of emitting an
  executor-unreachable localhost URL.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from pydantic import create_model, Field
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.exceptions import (
    HTTPNotFoundException,
    HTTPUnprocessableEntityException,
)
from app.core.pagination import Pagination
from app.sep.apps.framework.schema import AppSchema
from app.sep.apps.framework.script_helpers import build_artifact_download_url
from app.sep.apps.framework.script_source import ScriptExecuteWrite, ScriptSource
from app.sep.db import get_async_session_maker
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.constants import ARTIFACT_TYPE_SNIPPET
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.deps import (
    build_snippet_execution_meta,
    get_snippet_list_query,
    validate_snippet_filename,
)
from app.sep.snippets.list_query import SnippetListQuery
from app.sep.snippets.models.responses import build_snippet_response, SnippetResponse
from app.sep.snippets.models.snippet import (
    BaseSnippetArgs,
    EXECUTOR_HOSTS_INPUT_NAME,
    Snippet,
    SnippetExecutionMeta,
)
from app.sep.snippets.schema import (
    build_snippet_schema,
    evaluate_snippet_gates,
    SNIPPETS_PLUGIN_SCHEMA,
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
    :func:`~app.sep.snippets.deps.get_snippet_source`: it reads a
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


def snippet_not_found_detail(filename: str) -> str:
    """Return the client-facing 404 detail for an unresolved snippet filename.

    Single-sources the message shared by :func:`_load_script` and the ATW batch
    routes, which reconstruct it for filenames the batch loader left unresolved.

    :param filename: The requested snippet filename.
    :return: The 404 detail string.
    """
    return f"Snippet {filename!r} not found."


def _detach(session: AsyncSession, snippet: Snippet) -> Snippet:
    """Expunge a snippet from its session so it stays usable after the session closes.

    The request-less loaders below each read only loaded columns and file/meta
    ``cached_property`` values once their session closes — never a lazy
    relationship — so detaching the row keeps it usable without a live session.

    :param session: The open session the snippet was loaded in.
    :param snippet: The loaded snippet row.
    :return: The now-detached snippet.
    """
    session.expunge(snippet)
    return snippet


async def _load_script(filename: str) -> SnippetScript:
    """Resolve a snippet filename to a detached :class:`SnippetScript`.

    Opens a request-less session, fetches the row, and detaches it via
    :func:`_detach` so the script stays usable after the session closes.

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
            raise HTTPNotFoundException(detail=snippet_not_found_detail(filename))
        return SnippetScript(_detach(session, snippet))


async def _list_scripts(
    list_query: SnippetListQuery | None, pagination: Pagination | None
) -> tuple[list[SnippetScript], int]:
    """Return a filtered, sorted, paginated page of snippets and the filtered total.

    The Core sort/search, the snippets approval and service-type filters, and the
    filtered total are all pushed down to
    :meth:`~app.sep.snippets.crud.SnippetManager.snippet_list_page`, so the count and
    data queries share predicates and the ``total`` matches the visible page. The rows
    go through :func:`_detach` so they stay usable after the request-less session
    closes, mirroring :func:`_load_script`. The snippets list route always derives a
    query, so ``list_query`` and ``pagination`` are always supplied; the ``None``
    branches keep the hook honest against the framework's non-query call shapes, where an
    absent ``pagination`` means the whole set rather than a default-sized first page. A
    query with no pagination is answered unsliced but still filtered, searched, and
    ordered — the shape
    :meth:`~app.sep.apps.framework.list_query.InMemoryListQueryApplier.list_scripts`
    honours for a disk-backed source, so the two implementations of the one contract
    agree.

    :param list_query: The resolved sort/search/filter selections, or ``None`` for the
        manager's default ordering with no filters.
    :param pagination: The validated offset/limit window, or ``None`` for every
        matching snippet.
    :return: The wrapped snippets and the filtered total across all pages.
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        if pagination is None:
            rows = await (
                SnippetManager.list(session)
                if list_query is None
                else SnippetManager.snippet_list_all(session, list_query=list_query)
            )
            total = len(rows)
        else:
            page = await (
                SnippetManager.list_paginated(session, pagination=pagination)
                if list_query is None
                else SnippetManager.snippet_list_page(
                    session, list_query=list_query, pagination=pagination
                )
            )
            rows, total = page.items, page.total
        return [SnippetScript(_detach(session, snippet)) for snippet in rows], total


async def _load_scripts(filenames: Sequence[str]) -> dict[str, SnippetScript]:
    """Resolve several snippet filenames in one query, keyed by filename.

    The batch counterpart of :func:`_load_script`: one request-less session and a
    single ``filename IN (...)`` query answer the whole selection instead of one
    session and one query per filename. Each returned row is detached via
    :func:`_detach` before the session closes so the scripts stay usable
    afterwards. A filename whose row is absent, or whose file is missing on disk,
    is simply left out of the result — the framework's caller decides what an
    unresolved filename means.

    Each row is keyed by every requested spelling that matched it, not the stored
    ``filename``: the ``IN (...)`` match honours the column's collation, so on a
    case-insensitive collation a request for ``Check.sh`` matches row ``check.sh``.
    Folding the returned row back to each requested string keeps this hook's keys
    aligned with :func:`_load_script`, whose ``get_or_404`` compared inside the
    database, and means a selection carrying two case variants of one file
    (``Check.sh`` and ``check.sh``) resolves both rather than dropping one.
    Accent-insensitive collations remain a known boundary — casefolding covers
    case, not accents.

    :param filenames: The snippet filenames to resolve. Callers routing through
        :func:`~app.sep.apps.framework.script_source.resolve_scripts` pass a
        deduplicated, traversal-checked selection, but the hook is independently
        callable, so it re-validates each filename and tolerates duplicates.
    :return: A mapping of each resolved filename to its detached
        :class:`SnippetScript`; unresolved filenames are absent.
    :raises HTTPBadRequestException: When any filename is unsafe or malformed (the
        snippets-specific strictness the generic seam guard does not enforce).
    """
    for filename in filenames:
        validate_snippet_filename(filename)
    requested_by_casefold: dict[str, list[str]] = defaultdict(list)
    for filename in filenames:
        requested_by_casefold[filename.casefold()].append(filename)
    async_session = get_async_session_maker()
    async with async_session() as session:
        snippets = await SnippetManager.list(
            session, col(Snippet.filename).in_(filenames)
        )
        resolved: dict[str, Snippet] = {}
        for snippet in snippets:
            if not snippet.path.is_file():
                continue
            detached = _detach(session, snippet)
            requested = requested_by_casefold.get(
                snippet.filename.casefold(), [snippet.filename]
            )
            for spelling in requested:
                resolved[spelling] = detached
    return {filename: SnippetScript(snippet) for filename, snippet in resolved.items()}


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
    load_scripts=_load_scripts,
    build_form_schema=_build_form_schema,
    build_execution_meta=_build_execution_meta,
    list_response=_list_response,
    static_schema=SNIPPETS_PLUGIN_SCHEMA,
    list_response_model=SnippetResponse,
    list_query_dep=get_snippet_list_query,
)
