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

"""Corpus-wide authoring rules for builtin diagnostic-script front matter.

A run form is generated entirely from the YAML-in-comments front matter each
script under ``snippets/`` carries, so the form reads however the front matter
was authored. Every rule below is a convention about that authoring, and this
module is the check on it. The convention is the prose here, not the code.

Some of these defects are *silent*: the front matter validates, the snippet
ships, and the wrong thing renders with no parse error anywhere. ``description``
is dropped when its key is misspelled, an unrecognised ``type`` is rewritten to
``str``, and a ``placeholder`` on a non-string parameter never reaches the
rendered field. Those cannot fail loudly on their own, which is why they are
enforced here.

The authoring rules:

R1. ``description`` must say something ``label`` does not. A description that
    repeats its label, ignoring case and punctuation, leaves the form with one
    sentence of help text written twice.
R2. A snippet's own ``title`` and ``description``, every parameter ``label``
    and ``description``, and every choice label are read by an operator filling
    in a form or scanning the script list, not by someone reading the script's
    ``--help``. None of them may name a raw command-line flag (``--dbname``) or
    quote an invocation (``psql -d``); state what the value is for in product
    terms instead.
R3. A choice label may not carry a ``(default)`` suffix. The ``default:`` key
    already marks the default, and the renderer preselects it.
R4. A parameter naming an instant in time must declare ``type: datetime`` so
    the form renders a date-time picker rather than a free-text box. A
    parameter that declares ``choices`` is exempt however it is named. The
    choices, not the name, decide what it holds.
R7. Every top-level front-matter key must be one the application reads.
    ``BaseSnippet.meta`` is an untyped ``yaml.safe_load`` dict, so an unknown
    key, typically a misspelling of a real one, is accepted and its value lost.
R8. Every ``type:`` value must name a ``SnippetMetaParameterType`` member.
    ``set_default_type_if_unknown`` rewrites an unrecognised type to ``str``
    rather than raising, so this is checked against the raw YAML: by the time a
    parameter has validated, the defect is no longer visible on it.
R9. ``placeholder`` is only read when building a string field, so declaring one
    on any other parameter is dead. An unquoted YAML scalar is worse than dead:
    it reaches a string-typed field as an ``int``, and the whole parameter is
    discarded.
R10. A ``description`` may not restate a ``default:`` the front matter already
    declares; the form renders the default into the field. A description
    stating a default the front matter *cannot* express, such as one computed
    at run time, is not covered by this rule and is legitimate.
R11. A parameter whose script detects its value when the flag is omitted must
    not declare a ``default:``. A default is always sent, so it would suppress
    the detection the script performs.
R12. Every script must declare ``diagnostic_categories:`` with a list value,
    populated or empty. The diagnostics browser reaches a script only through
    that key, so an omitted declaration and a deliberate exclusion are
    otherwise indistinguishable. Search-only is the empty list; a valueless
    key parses to ``None``, which the reader logs and discards.
R13. Every declared category must name an ``ATWCategory`` member. The listing
    matches ``category.name``, so a name the taxonomy does not define places
    the script in no cell and is discarded without a warning.

The numbering skips R5 and R6, which stay judgement calls and are not checked
here: whether a ``placeholder`` shows a literal the script would itself use
(which belongs in ``default:``) or an illustrative example, and whether a
``required`` parameter has a defensible default. Both need the script's own
fallback path read.

Parameters that fail validation are absent from ``validated_parameters``, so
the rules keyed on validated parameters skip them; the corpus-wide check that
every snippet parses without errors is what keeps that from hiding anything.
"""

import re

import pytest

from app.extensions.apps.atw.categories import ATWCategory
from app.extensions.snippets.checksums import BUILTIN_CHECKSUM_MANIFEST
from app.extensions.snippets.models.meta import (
    META_KEY_DESCRIPTION,
    META_KEY_DIAGNOSTIC_CATEGORIES,
    META_KEY_TITLE,
    SnippetMetaParameter,
    SnippetMetaParameterType,
    SUPPORTED_META_KEYS,
)
from app.extensions.snippets.models.snippet import BaseSnippet
from tests.app.extensions.snippets.snippet_corpus import SNIPPET_FILENAMES

KNOWN_PARAMETER_TYPES = frozenset(
    member.name.lower() for member in SnippetMetaParameterType
)

KNOWN_CATEGORY_NAMES = frozenset(member.name for member in ATWCategory)

_MISSING = object()
"""Sentinel separating an absent category key from one declared with no value."""

TIMESTAMP_PARAMETER_NAMES = frozenset(
    {
        "date",
        "end",
        "end-time",
        "start",
        "start-time",
        "time",
        "timestamp",
    }
)

AUTO_DETECTING_PARAMETERS = frozenset(
    {
        ("mongodb_ftdc_collect.sh", "data-dir"),
        ("mongodb_log_extractor.sh", "log-file"),
        ("mongodb_pbm_diagnostics.sh", "mongo-log-file"),
        ("mongodb_pbm_diagnostics.sh", "mongodb-uri"),
        ("mongodb_pt_pmp.sh", "pid"),
        ("postgresql_config_files.sh", "auto-config-file"),
        ("postgresql_config_files.sh", "config-file"),
        ("postgresql_config_files.sh", "data-dir"),
        ("postgresql_log_extractor.sh", "log-file"),
        ("postgresql_query_tuning.sh", "explain-options"),
        ("proxysql_log_extractor.sh", "log-file"),
    }
)

_LONG_FLAG_RE = re.compile(r"(?<![\w-])--[A-Za-z][\w-]*")
_TOOL_INVOCATION_RE = re.compile(
    r"\b(?:psql|pg_\w+|mysql\w*|mongosh?|mongod\w*|pbm|pt-[\w-]+|du|df)\s+-[A-Za-z]+\b"
)
_NON_ALPHANUMERIC_RE = re.compile(r"[^0-9a-z]+")


def _normalize(text: str) -> str:
    """Return the letters and digits of user-facing text, lowercased.

    :param text: The text to normalize.
    :return: The normalized text.
    """
    return _NON_ALPHANUMERIC_RE.sub("", text.lower())


def _user_facing_texts(parameter: SnippetMetaParameter) -> list[tuple[str, str]]:
    """Collect the strings a parameter shows to whoever fills in the form.

    :param parameter: The parameter to read.
    :return: Pairs of front-matter key and the text declared under it.
    """
    texts = [
        (key, value)
        for key, value in (
            ("label", parameter.label),
            ("description", parameter.description),
        )
        if value
    ]
    texts.extend(
        (f"choice {choice['value']!r} label", label)
        for choice in parameter.choices or []
        if (label := choice.get("label"))
    )
    return texts


def _raw_parameters(snippet: BaseSnippet) -> list[dict[str, object]]:
    """Read the parameter declarations as YAML parsed them.

    Rules about a key the parameter model discards, or rewrites during
    validation, can only be checked here.

    :param snippet: The snippet whose front matter to read.
    :return: The raw parameter mappings, skipping any non-mapping entry.
    """
    return [
        param
        for param in snippet.meta.get("parameters") or []
        if isinstance(param, dict)
    ]


async def _load(filename: str) -> BaseSnippet:
    """Load a snippet through the production parsing path.

    :param filename: The snippet filename, relative to the snippets directory.
    :return: The parsed snippet.
    """
    return await BaseSnippet.from_path(filename, update_meta=True)


def test_corpus_enumeration_skips_the_checksum_manifest():
    """Skip the checksum manifest, which shares the directory but is not a snippet."""
    assert SNIPPET_FILENAMES, "no snippets found to check"
    assert BUILTIN_CHECKSUM_MANIFEST not in SNIPPET_FILENAMES


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_snippet_parameters_parse_without_errors(filename):
    """Parse every snippet's parameters, so no field is silently dropped."""
    snippet = await _load(filename)

    assert snippet.validated_parameters.errors == [], (
        f"{filename} has front-matter parameter errors"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_description_says_more_than_label(filename):
    """Verify no description merely repeats its label (R1)."""
    snippet = await _load(filename)

    for param in snippet.validated_parameters.parameters:
        if not (param.label and param.description):
            continue
        assert _normalize(param.description) != _normalize(param.label), (
            f"{filename}:{param.name} description repeats its label"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_no_command_line_syntax_in_user_facing_text(filename):
    """Verify form text names what a value is for, not the flag carrying it (R2)."""
    snippet = await _load(filename)

    texts = [
        (META_KEY_TITLE, snippet.meta.get(META_KEY_TITLE)),
        (META_KEY_DESCRIPTION, snippet.meta.get(META_KEY_DESCRIPTION)),
    ]
    texts.extend(
        (f"{param.name} {key}", text)
        for param in snippet.validated_parameters.parameters
        for key, text in _user_facing_texts(param)
    )

    for key, text in texts:
        if not isinstance(text, str):
            continue
        flag = _LONG_FLAG_RE.search(text) or _TOOL_INVOCATION_RE.search(text)
        assert flag is None, (
            f"{filename} {key} names command-line syntax {flag.group(0)!r}: {text!r}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_choice_labels_omit_default_suffix(filename):
    """Verify no choice label restates the declared default (R3)."""
    snippet = await _load(filename)

    offenders = [
        f"{param.name}:{choice['value']}"
        for param in snippet.validated_parameters.parameters
        for choice in param.choices or []
        if "(default)" in (choice.get("label") or "").lower()
    ]

    assert offenders == [], (
        f"{filename} choice labels restate the declared default: {offenders}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_timestamp_parameters_declare_datetime_type(filename):
    """Verify an instant in time renders as a picker, not a free-text box (R4)."""
    snippet = await _load(filename)

    for param in snippet.validated_parameters.parameters:
        if param.name not in TIMESTAMP_PARAMETER_NAMES or param.choices:
            continue
        assert param.py_type is SnippetMetaParameterType.DATETIME, (
            f"{filename}:{param.name} names an instant in time but declares "
            f"type {param.py_type.name.lower()!r}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_top_level_keys_are_read_by_the_application(filename):
    """Verify every top-level key is one the application reads (R7)."""
    snippet = await _load(filename)

    unknown = sorted(set(snippet.meta) - SUPPORTED_META_KEYS)
    assert unknown == [], f"{filename} declares unread front-matter keys {unknown}"


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_every_snippet_declares_its_browser_membership(filename):
    """Verify every script records a browser-membership decision (R12)."""
    snippet = await _load(filename)

    declared = snippet.meta.get(META_KEY_DIAGNOSTIC_CATEGORIES, _MISSING)
    assert declared is not _MISSING, (
        f"{filename} declares no {META_KEY_DIAGNOSTIC_CATEGORIES!r}, so whether it "
        "belongs in the diagnostics browser is unrecorded"
    )
    assert isinstance(declared, list), (
        f"{filename} declares {META_KEY_DIAGNOSTIC_CATEGORIES!r} as "
        f"{type(declared).__name__}; search-only is the empty list, not a bare key"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_declared_categories_name_taxonomy_members(filename):
    """Verify every declared category names an ``ATWCategory`` member (R13)."""
    snippet = await _load(filename)

    declared = snippet.meta.get(META_KEY_DIAGNOSTIC_CATEGORIES)
    if not isinstance(declared, list):
        pytest.skip(f"{filename} has no list-valued declaration; R12 reports it")
    unknown = [
        category
        for category in declared
        if not isinstance(category, str) or category not in KNOWN_CATEGORY_NAMES
    ]
    assert unknown == [], (
        f"{filename} declares categories the taxonomy does not define: {unknown}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_parameter_types_are_recognised(filename):
    """Verify every declared parameter type is recognised (R8)."""
    snippet = await _load(filename)

    for param in _raw_parameters(snippet):
        declared = param.get("type")
        if declared is None:
            continue
        assert declared in KNOWN_PARAMETER_TYPES, (
            f"{filename}:{param.get('name')!r} declares unknown type "
            f"{declared!r}, which would silently render as a text box"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_placeholder_only_on_plain_string_parameters(filename):
    """Verify a placeholder is declared only where it renders (R9)."""
    snippet = await _load(filename)

    for param in _raw_parameters(snippet):
        if "placeholder" not in param:
            continue
        declared = param.get("type", "str")
        assert declared == "str", (
            f"{filename}:{param.get('name')!r} declares a placeholder on a "
            f"{declared!r} parameter, where it is never rendered"
        )
        choices = param.get("choices") or param.get("options")
        assert not choices, (
            f"{filename}:{param.get('name')!r} declares a placeholder beside "
            "choices, where it is never rendered"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_description_does_not_restate_declared_default(filename):
    """Verify no description restates a default the front matter declares (R10)."""
    snippet = await _load(filename)

    for param in snippet.validated_parameters.parameters:
        if not str(param.default or "") or not param.description:
            continue
        restatement = re.search(
            rf"defaults?(?:\s+to|:)\s*`?{re.escape(str(param.default))}`?\b",
            param.description,
            re.IGNORECASE,
        )
        assert restatement is None, (
            f"{filename}:{param.name} description restates its declared "
            f"default: {restatement.group(0)!r}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", SNIPPET_FILENAMES)
async def test_auto_detecting_parameters_declare_no_default(filename):
    """Verify an auto-detecting parameter declares no default (R11)."""
    snippet = await _load(filename)

    for param in snippet.validated_parameters.parameters:
        if (filename, param.name) not in AUTO_DETECTING_PARAMETERS:
            continue
        assert param.default is None, (
            f"{filename}:{param.name} is detected by the script when omitted, "
            f"but declares default {param.default!r}"
        )
