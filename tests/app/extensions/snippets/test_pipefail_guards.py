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

"""Corpus-wide check that piped command substitutions cannot abort a snippet.

Most builtin scripts run under ``set -euo pipefail``. Under those options an
assignment such as::

    MONGOD_PID=$(pgrep -x mongod 2> /dev/null | head -1)

is a simple command whose exit status is the substitution's, the substitution's
status is the pipeline's, and ``pipefail`` makes the pipeline's status the first
non-zero one in it. ``pgrep`` exits 1 when nothing matches, so on a host where
the process is not running the script dies on that line: before the fallbacks the
line was meant to lead into, before the not-found message, with nothing on either
stream. The value being *allowed* to be empty is exactly why the status must not
be trusted.

The guard the corpus already uses is ``|| true`` at the end of the pipeline,
inside the substitution, so only the substitution's status is swallowed and the
consumer still tests the value it received. Any construct bash itself treats as
guarded also counts: a ``||`` branch ending the substitution, an ``||`` or ``&&``
list continuing the statement, or the assignment sitting in an ``if``, ``elif``,
``while`` or ``until`` condition. The guard has to cover the *last* statement the
body runs, because that statement's status is the substitution's: a body ending in
a bare command is unguarded however the statements above it are written.

A declaration builtin is the one shape that cannot abort. ``local x=$(a | b)``,
and the same with ``declare``, ``readonly``, ``export`` or ``typeset``, exits with
the *builtin's* status, not the substitution's, so ``set -e`` never sees the
failure. Those lines hide an error rather than propagating one, which is
``shellcheck``'s SC2155, not this check's contract.

The check classifies no commands. It cannot know that ``printf`` and ``sed`` never
fail on an in-memory string while ``du`` fails on an unreadable directory, and a
list of commands "known to fail" is exactly what missed the ``du`` site this check
was written for. An assignment that reads from a pipeline is flagged unless it is
guarded or the line immediately above it carries::

    # pipefail-safe: <why this pipeline cannot exit non-zero>

The reason is mandatory. A marker with no reason, or one not followed by a site
this check would otherwise flag, is itself a defect, so a marker cannot outlive
the line it was written for.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from textwrap import dedent

import pytest

from app.extensions.snippets.config import snippets_settings
from tests.app.extensions.snippets.snippet_corpus import SHELL_SNIPPET_FILENAMES

ERREXIT_RE = re.compile(
    r"^[ \t]*set[ \t]+(?:\S+[ \t]+)*?(?:-[a-zA-Z]*e[a-zA-Z]*\b|-o[ \t]+errexit\b)",
    re.MULTILINE,
)
PIPEFAIL_RE = re.compile(
    r"^[ \t]*set[ \t]+-\S*(?:[ \t]+\S+)*?[ \t]*\bpipefail\b", re.MULTILINE
)
PIPEFAIL_SAFE_MARKER_RE = re.compile(r"^\s*#\s*pipefail-safe\b:?(?P<reason>.*)$")
ASSIGNMENT_RE = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"(?P<condition>(?:(?:if|elif|while|until)[ \t]+)?(?:![ \t]+)?)"
    r"[A-Za-z_]\w*(?:\[[^\]]*\])?\+?=[\"']?\$\((?!\()",
    re.MULTILINE,
)
SINGLE_PIPE_RE = re.compile(r"(?<!\|)\|(?!\|)")
CONTINUING_OPERATORS = ("|", "&&")


def _continues_the_statement(body: str, index: int) -> bool:
    """Return whether the separator at ``index`` is a line break inside a statement.

    A newline that follows a pipe or a list operator carries the statement on to the
    next line rather than ending it.

    :param body: The bare substitution body.
    :param index: The index of the ``;`` or newline to classify.
    :return: ``True`` when the statement continues past it.
    """
    return body[index] == "\n" and body[:index].rstrip(" \t").endswith(
        CONTINUING_OPERATORS
    )


def last_statement(body: str) -> str:
    """Return the last statement a substitution body runs.

    The substitution's status is that statement's, so a guard on an earlier one does
    not cover the assignment: a body that guards ``a | b`` and then runs a bare
    ``c`` on the next line still exits on ``c``.

    :param body: The bare substitution body.
    :return: The last non-blank statement, or an empty string for a blank body.
    """
    depth = 0
    start = 0
    statements: list[str] = []
    for index, char in enumerate(body):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and char in ";\n" and not _continues_the_statement(body, index):
            statements.append(body[start:index])
            start = index + 1
    statements.append(body[start:])
    return next(
        (statement for statement in reversed(statements) if statement.strip()), ""
    )


@dataclass(frozen=True)
class PipedAssignment:
    """Describe one assignment whose value comes from a piped command substitution.

    :param first_line: The 1-based line the assignment starts on.
    :param last_line: The 1-based line the substitution closes on.
    :param statement: The assignment's first line, stripped.
    :param body: The substitution body with quoted text, nested substitutions and
        comments removed, so a ``|`` in it is a pipeline operator.
    :param tail: The text following the closing parenthesis on its line.
    :param in_condition: Whether the assignment is the test of a compound command.
    """

    first_line: int
    last_line: int
    statement: str
    body: str
    tail: str
    in_condition: bool

    def is_guarded(self) -> bool:
        """Return whether bash would let this assignment fail without exiting.

        A body whose last statement runs no pipeline is unguarded: either its status
        reaches ``set -e`` directly, or the shape is one this check does not model.

        :return: ``True`` when the pipeline's status cannot reach ``set -e``.
        """
        if self.in_condition:
            return True
        tail = self.tail.lstrip().lstrip("\"'").lstrip()
        if tail.startswith(("||", "&&")):
            return True
        statement = last_statement(self.body)
        pipes = [match.end() for match in SINGLE_PIPE_RE.finditer(statement)]
        if not pipes:
            return False
        return "||" in statement[max(pipes) :]


@dataclass(frozen=True)
class Offence:
    """Describe one line the check rejects.

    :param line: The 1-based line the offence anchors to.
    :param reason: What is wrong with it.
    :param statement: The offending line, stripped.
    """

    line: int
    reason: str
    statement: str

    def __str__(self) -> str:
        """Format the offence as ``line: reason: statement``.

        :return: The one-line rendering.
        """
        return f"{self.line}: {self.reason}: {self.statement}"


def declares_errexit_and_pipefail(text: str) -> bool:
    """Return whether a script enables both ``set -e`` and ``pipefail``.

    :param text: The script source.
    :return: ``True`` when both options are switched on somewhere in the script.
    """
    return bool(ERREXIT_RE.search(text) and PIPEFAIL_RE.search(text))


def _skip_arithmetic(text: str, pos: int) -> int:
    """Return the index just past the ``))`` closing the ``$((`` at ``pos``.

    :param text: The script source.
    :param pos: The index of the ``$`` opening the arithmetic expansion.
    :return: The index after the expansion, or the text length when unterminated.
    """
    depth = 0
    index = pos + 1
    while index < len(text):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def _skip_expansion(text: str, index: int) -> int | None:
    """Return the index past an escape or expansion, whether or not it is quoted.

    These are the constructs a ``|`` or ``)`` can hide behind at every level of the
    walk: inside double quotes a ``$(`` still opens a substitution, so both walkers
    have to consume it the same way.

    :param text: The script source.
    :param index: The index to inspect.
    :return: The index just past the construct, or ``None`` when none starts here.
    """
    if text[index] == "\\":
        return index + 2
    if text.startswith("$((", index):
        return _skip_arithmetic(text, index)
    if text.startswith("$(", index):
        return _consume_substitution(text, index + 2)[0]
    return None


def _skip_opaque(text: str, index: int) -> int | None:
    """Return the index past a construct that hides its content from the parser.

    Single- and double-quoted strings, arithmetic expansions and nested
    substitutions are consumed whole: a ``|`` or ``)`` inside them is data, not
    syntax, at the level being walked.

    :param text: The script source.
    :param index: The index to inspect.
    :return: The index just past the construct, or ``None`` when none starts here.
    """
    if (skipped := _skip_expansion(text, index)) is not None:
        return skipped
    if text[index] == "'":
        closing = text.find("'", index + 1)
        return len(text) if closing < 0 else closing + 1
    if text[index] == '"':
        return _skip_double_quoted(text, index + 1)
    return None


def _consume_substitution(text: str, pos: int) -> tuple[int, str]:
    """Walk a ``$(`` substitution and return where it ends and its bare body.

    Quoted text, nested expansions and comments are dropped, so the body that
    comes back contains a ``|`` only where the shell would see a pipe.

    :param text: The script source.
    :param pos: The index just past the opening ``$(``.
    :return: The index just past the closing ``)`` and the bare body.
    """
    body: list[str] = []
    depth = 0
    index = pos
    while index < len(text):
        if (skipped := _skip_opaque(text, index)) is not None:
            index = skipped
            continue
        char = text[index]
        if char == "#" and (index == 0 or text[index - 1].isspace()):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                return index + 1, "".join(body)
            depth -= 1
        body.append(char)
        index += 1
    return len(text), "".join(body)


def _skip_double_quoted(text: str, pos: int) -> int:
    """Return the index just past the ``"`` closing the string opened before ``pos``.

    A substitution inside the string is consumed whole so a ``)`` in it cannot be
    mistaken for the closing parenthesis of the substitution being walked. A ``'``
    is not: inside double quotes it is an ordinary character.

    :param text: The script source.
    :param pos: The index just past the opening ``"``.
    :return: The index after the closing quote, or the text length when unterminated.
    """
    index = pos
    while index < len(text):
        if (skipped := _skip_expansion(text, index)) is not None:
            index = skipped
        elif text[index] == '"':
            return index + 1
        else:
            index += 1
    return len(text)


def iter_piped_assignments(text: str) -> Iterator[PipedAssignment]:
    """Yield every assignment whose value is a command substitution with a pipe.

    :param text: The script source.
    :return: The assignments, in source order.
    """
    pos = 0
    while (match := ASSIGNMENT_RE.search(text, pos)) is not None:
        end, body = _consume_substitution(text, match.end())
        pos = end
        if not SINGLE_PIPE_RE.search(body):
            continue
        line_end = text.find("\n", end)
        line_end = len(text) if line_end < 0 else line_end
        statement_end = text.find("\n", match.start())
        statement_end = len(text) if statement_end < 0 else statement_end
        yield PipedAssignment(
            first_line=text.count("\n", 0, match.start()) + 1,
            last_line=text.count("\n", 0, end) + 1,
            statement=text[match.start() : statement_end].strip(),
            body=body,
            tail=text[end:line_end],
            in_condition=bool(match.group("condition").strip()),
        )


def find_offenders(text: str) -> list[Offence]:
    """Return every unguarded piped assignment and every misused marker.

    A script that does not enable both ``set -e`` and ``pipefail`` cannot abort
    this way and yields nothing.

    :param text: The script source.
    :return: The offences, in line order.
    """
    if not declares_errexit_and_pipefail(text):
        return []
    lines = text.splitlines()
    exempt_lines: set[int] = set()
    offences: list[Offence] = []
    for number, line in enumerate(lines, start=1):
        marker = PIPEFAIL_SAFE_MARKER_RE.match(line)
        if marker is None:
            continue
        if not marker.group("reason").strip():
            offences.append(
                Offence(number, "pipefail-safe marker carries no reason", line.strip())
            )
            continue
        exempt_lines.add(number + 1)
    justified: set[int] = set()
    for site in iter_piped_assignments(text):
        if site.is_guarded():
            continue
        if site.first_line in exempt_lines:
            justified.add(site.first_line)
            continue
        offences.append(
            Offence(
                site.first_line,
                "assignment reads from an unguarded pipeline; append `|| true` inside the "
                "substitution or justify it with a `# pipefail-safe:` marker above",
                site.statement,
            )
        )
    offences.extend(
        Offence(
            exempt - 1,
            "pipefail-safe marker does not precede an unguarded piped assignment",
            lines[exempt - 2].strip(),
        )
        for exempt in exempt_lines - justified
    )
    return sorted(offences, key=lambda offence: offence.line)


def _script(body: str, *, options: str = "set -euo pipefail") -> str:
    """Wrap a shell fragment in the preamble the builtin scripts use.

    :param body: The shell fragment under test.
    :param options: The ``set`` line to declare, or an empty string for none.
    :return: The complete script source.
    """
    return f"#!/bin/bash\n{options}\n{dedent(body)}"


def _offending_lines(text: str) -> list[int]:
    """Return the line numbers :func:`find_offenders` reports for ``text``.

    :param text: The script source.
    :return: The offending line numbers.
    """
    return [offence.line for offence in find_offenders(text)]


class TestDeclaresErrexitAndPipefail:
    """Scope the check to scripts that switch on both options."""

    @pytest.mark.parametrize(
        "options",
        [
            "set -euo pipefail",
            "set -eo pipefail",
            "set -e\nset -o pipefail",
            "set -o errexit\nset -o pipefail",
            "set -xe\nset -uo pipefail",
            "set -o pipefail -e",
            "set -o pipefail -eu",
            "set -o pipefail; set -e",
        ],
    )
    def test_both_options_are_recognised(self, options):
        """Detect every spelling of errexit plus pipefail the corpus uses."""
        assert declares_errexit_and_pipefail(_script("", options=options))

    @pytest.mark.parametrize(
        "options",
        [
            "",
            "set -e",
            "set -u",
            "set -o pipefail",
            "set -uo pipefail",
            "set +o pipefail",
            "set -e\nset +o pipefail",
        ],
    )
    def test_one_option_alone_is_out_of_scope(self, options):
        """Leave a script alone when either option is missing or switched off."""
        assert not declares_errexit_and_pipefail(_script("", options=options))

    def test_out_of_scope_script_yields_no_offences(self):
        """Report nothing for the pattern in a script that cannot abort on it."""
        text = _script("X=$(pgrep -x mongod | head -1)\n", options="set -e")
        assert find_offenders(text) == []


class TestPipedAssignmentDetection:
    """Find every assignment shape the corpus writes, and only those."""

    @pytest.mark.parametrize(
        "line",
        [
            "X=$(pgrep -x mongod 2> /dev/null | head -1)",
            'X="$(pgrep -x mongod 2> /dev/null | head -1)"',
            "X+=$(a | b)",
            "ARR[0]=$(a | b)",
            "    X=$(a | b)",
            "X=$(a |& b)",
        ],
    )
    def test_assignment_shapes_are_flagged(self, line):
        """Flag each assignment form that takes its value from a piped substitution."""
        assert _offending_lines(_script(line + "\n")) == [3], line

    @pytest.mark.parametrize(
        "line",
        [
            "local x=$(a | b)",
            "declare -r X=$(a | b)",
            "readonly X=$(a | b)",
            'export X="$(a | b)"',
            "typeset -i x=$(a | b)",
        ],
    )
    def test_declaration_builtins_are_ignored(self, line):
        """Leave the shapes whose status is the builtin's, not the substitution's."""
        assert _offending_lines(_script(line + "\n")) == [], line

    def test_multi_line_substitution_is_flagged_at_its_first_line(self):
        """Anchor a body spanning several lines to the line the assignment starts on."""
        text = _script(
            """
            logs=$(
                find "$DIR" -maxdepth 1 -type f \\
                    -printf '%T@ %p\\n' 2> /dev/null |
                    sort -n | tail -n 4 | cut -d' ' -f2-
            )
            """
        )
        assert _offending_lines(text) == [4]

    @pytest.mark.parametrize(
        "line",
        [
            "X=$(pgrep -x mongod)",
            "X=$(a || b)",
            "X=$(a && b)",
            "X=$(awk '/a|b/ { print }' file)",
            'X=$(grep "a|b" file)',
            "X=$(echo $(a | b || true))",
            "X=$(echo $(a | b))",
            "X=$(( a | b ))",
            "X=$(a) | b",
            "# X=$(a | b)",
            "X=$(a \\| b)",
        ],
    )
    def test_shapes_without_a_pipeline_are_ignored(self, line):
        """Ignore a ``|`` that is not a pipeline operator of the substitution."""
        assert _offending_lines(_script(line + "\n")) == [], line

    def test_comment_inside_body_is_not_a_pipeline(self):
        """Drop a comment line inside a multi-line substitution before looking for pipes."""
        text = _script(
            """
            X=$(
                # a | b
                a
            )
            """
        )
        assert _offending_lines(text) == []

    def test_quoted_parenthesis_does_not_close_the_substitution(self):
        """Keep walking past a ``)`` inside quotes so the pipe after it is still seen."""
        text = _script("X=$(printf ')' | head -1)\n")
        assert _offending_lines(text) == [3]

    def test_sites_are_reported_in_source_order(self):
        """List every offence in a script, each on its own line."""
        text = _script(
            """
            A=$(a | b)
            B=$(c | d || true)
            C=$(e | f)
            """
        )
        assert _offending_lines(text) == [4, 6]


class TestGuards:
    """Treat as guarded whatever bash itself treats as guarded."""

    @pytest.mark.parametrize(
        "line",
        [
            "X=$(pgrep -x mongod 2> /dev/null | head -1 || true)",
            'X="$(pgrep -x mongod 2> /dev/null | head -1 || true)"',
            "X=$(a | b || :)",
            "X=$(a | b || echo default)",
            "X=$(a | b) || true",
            'X="$(a | b)" || true',
            'X=$(a | b) || X=""',
            "X=$(a | b) && echo found",
            "if ! X=$(a | b); then",
            "if X=$(a | b); then",
            "elif X=$(a | b); then",
            "while X=$(a | b); do",
            "until X=$(a | b); do",
            "! X=$(a | b)",
        ],
    )
    def test_guarded_shapes_are_not_flagged(self, line):
        """Accept every guard the corpus uses and every one bash honours."""
        assert _offending_lines(_script(line + "\n")) == [], line

    def test_guard_on_the_closing_line_of_a_multi_line_body_counts(self):
        """Read the guard from the last pipeline stage wherever the body ends."""
        text = _script(
            """
            logs=$(
                find "$DIR" -maxdepth 1 -type f 2> /dev/null |
                    sort -n | tail -n 4 | cut -d' ' -f2- || true
            )
            """
        )
        assert _offending_lines(text) == []

    def test_guard_after_the_closing_parenthesis_of_a_multi_line_body_counts(self):
        """Accept a ``||`` list that follows the substitution on its closing line."""
        text = _script(
            """
            glob=$(
                psql -tA -c "select 1" 2> /dev/null |
                    head -1
            ) || glob=""
            """
        )
        assert _offending_lines(text) == []

    @pytest.mark.parametrize(
        "line",
        [
            "X=$(a | b || c | d)",
            "X=$(a || b | c)",
            "X=$(a | b; c)",
            "X=$(a | b && c)",
        ],
    )
    def test_pipeline_still_last_is_flagged(self, line):
        """Flag a body whose final status is still a pipeline's."""
        assert _offending_lines(_script(line + "\n")) == [3], line

    def test_guard_on_an_earlier_statement_does_not_cover_the_body(self):
        """Flag a body whose guarded pipeline is followed by another statement."""
        text = _script(
            """
            X=$(
                true | false || true
                false
            )
            """
        )
        assert _offending_lines(text) == [4]

    def test_a_guard_on_the_last_of_several_statements_counts(self):
        """Accept a body whose closing statement carries the guard."""
        text = _script(
            """
            X=$(
                echo start
                true | false || true
            )
            """
        )
        assert _offending_lines(text) == []


class TestExemptionMarker:
    """Silence a safe site on an explicit, reasoned marker, and on nothing else."""

    def test_marker_with_reason_silences_the_next_line(self):
        """Accept a marker that names why the pipeline cannot fail."""
        text = _script(
            """
            # pipefail-safe: printf and sed cannot fail on an in-memory string
            pattern=$(printf '%s' "$name" | sed 's/%[A-Za-z]/*/g')
            """
        )
        assert find_offenders(text) == []

    @pytest.mark.parametrize(
        "marker", ["# pipefail-safe", "# pipefail-safe:", "#pipefail-safe:   "]
    )
    def test_marker_without_reason_is_an_offence(self, marker):
        """Reject a marker that asserts safety without saying why."""
        text = _script(f"{marker}\nX=$(a | b)\n")
        offences = find_offenders(text)
        assert [offence.line for offence in offences] == [3, 4]
        assert "no reason" in offences[0].reason

    def test_marker_two_lines_above_does_not_silence(self):
        """Bind a marker to the line directly below it and nothing further."""
        text = _script(
            """
            # pipefail-safe: some reason
            Y=1
            X=$(a | b)
            """
        )
        assert [offence.line for offence in find_offenders(text)] == [4, 6]

    def test_marker_before_an_unpiped_line_is_stale(self):
        """Reject a marker whose line no longer needs it."""
        text = _script(
            """
            # pipefail-safe: some reason
            X=$(a)
            """
        )
        offences = find_offenders(text)
        assert [offence.line for offence in offences] == [4]
        assert "does not precede" in offences[0].reason

    def test_marker_before_a_guarded_line_is_stale(self):
        """Reject a marker on a line already guarded by ``|| true``."""
        text = _script(
            """
            # pipefail-safe: some reason
            X=$(a | b || true)
            """
        )
        assert [offence.line for offence in find_offenders(text)] == [4]

    def test_marker_does_not_silence_a_second_site(self):
        """Exempt one site per marker, not every site that follows it."""
        text = _script(
            """
            # pipefail-safe: some reason
            X=$(a | b)
            Y=$(c | d)
            """
        )
        assert [offence.line for offence in find_offenders(text)] == [6]


class TestCalibration:
    """Classify the exact lines that motivated this check the way it promises."""

    @pytest.mark.parametrize(
        "line",
        [
            "MONGOD_PID=$(pgrep -x mongod 2> /dev/null | head -1)",
            "MONGO_PID=$(pgrep -x 'mongo[ds]' 2> /dev/null | head -1)",
            'FTDC_FILES=$(find "$FTDC_DIR" -maxdepth 1 -type f | sort)',
            'TOTAL_SIZE=$(du -sh "$FTDC_DIR" | cut -f1)',
            'FILE_COUNT=$(find "$FTDC_DIR" -maxdepth 1 -type f | wc -l)',
        ],
    )
    def test_abort_capable_sites_are_flagged(self, line):
        """Flag each site that terminated its script on a host without the process."""
        assert _offending_lines(_script(line + "\n")) == [3], line

    @pytest.mark.parametrize(
        "line",
        [
            "log_pattern=$(printf '%s' \"$log_filename\" | sed 's/%[A-Za-z]/*/g')",
            "VER_NUM=$(echo \"$VER_NUM\" | tr -d '[:space:]')",
        ],
    )
    def test_structurally_safe_sites_need_a_marker(self, line):
        """Flag a safe site until its author says why it is safe; no command is trusted."""
        assert _offending_lines(_script(line + "\n")) == [3], line
        marked = _script(f"# pipefail-safe: builtins on an in-memory string\n{line}\n")
        assert _offending_lines(marked) == [], line


class TestCorpus:
    """Hold every builtin script to the guard contract."""

    def test_the_corpus_is_not_empty(self):
        """Fail loudly rather than pass by covering no script at all."""
        assert SHELL_SNIPPET_FILENAMES, "no shell snippets found to check"

    @pytest.mark.parametrize("filename", SHELL_SNIPPET_FILENAMES)
    def test_no_unguarded_piped_assignment(self, filename):
        """Reject any unguarded piped assignment or misused marker in a builtin script."""
        text = (snippets_settings.SNIPPETS_DIR / filename).read_text(encoding="utf-8")
        offences = find_offenders(text)
        assert offences == [], "\n".join(
            f"{filename}:{offence}" for offence in offences
        )
