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

"""Tests for the ``xtrabackup_quiet`` per-file copy line filter.

The payload script cannot be exec'd in the test environment (it imports boto3
and other heavy runtime deps), so ``_COPY_LINE_RE`` is extracted from the
source text and recompiled — giving us the actual production pattern without
pulling in the full dependency tree.
"""

import ast
import pathlib
import re

import pytest

_PAYLOAD_PATH = (
    pathlib.Path(__file__).parents[5] / "app/sep/apps/mysql_backups/xtrabackup_payload"
)


def _extract_copy_line_re() -> re.Pattern:
    """Extract and compile ``_COPY_LINE_RE`` from the payload source via AST.

    Uses ``ast.parse`` rather than regex-on-source so that refactors to
    string literal style, quoting, or line wrapping do not break this test.
    """
    source = _PAYLOAD_PATH.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_COPY_LINE_RE"
            and isinstance(node.value, ast.Call)
            and node.value.args
        ):
            try:
                pattern = ast.literal_eval(node.value.args[0])
            except ValueError:
                continue
            return re.compile(pattern)
    raise RuntimeError(
        f"_COPY_LINE_RE not found in {_PAYLOAD_PATH}. "
        "Has the constant been renamed or removed?"
    )


_COPY_LINE_RE = _extract_copy_line_re()


class TestCopyLineRegexStructure:
    """Structural guarantees: the regex must be compiled and properly anchored."""

    def test_is_compiled_pattern(self):
        """``_COPY_LINE_RE`` must be a pre-compiled ``re.Pattern``, not a string.

        Compiling at module level prevents per-line recompilation overhead
        in the hot backup stdout loop.
        """
        assert isinstance(_COPY_LINE_RE, re.Pattern)

    def test_is_anchored_at_start(self):
        """Pattern must begin with ``^`` so mid-line content cannot match."""
        assert _COPY_LINE_RE.pattern.startswith("^")

    def test_constant_is_present_in_payload_source(self):
        """``_COPY_LINE_RE`` must remain defined in the payload script.

        If the constant is renamed or removed, this test fails loudly rather
        than letting the extraction silently fall back to a wrong pattern.
        """
        assert "_COPY_LINE_RE" in _PAYLOAD_PATH.read_text()


class TestCopyLineRegexFiltersProgressLines:
    """Lines that MUST be dropped when ``xtrabackup_quiet=True``."""

    @pytest.mark.parametrize(
        "line",
        [
            # Standard two-digit thread prefix
            "[01] NT: Copying /var/lib/mysql/db1/table1.ibd to /backup/db1/table1.ibd\n",
            "[01] NT: Finished copying /var/lib/mysql/db1/table1.ibd\n",
            "[01] ...db1/table1.ibd: 45% copied\n",
            "[02] ...schema/very_long_table_name.ibd: 100% copied\n",
            # System tablespace file (ibdata1.ibd has no table-level path segment)
            "[01] NT: Copying /var/lib/mysql/ibdata1.ibd to /backup/ibdata1.ibd\n",
            "[01] NT: Finished copying /var/lib/mysql/ibdata1.ibd\n",
        ],
    )
    def test_matches_standard_copy_progress_lines(self, line: str):
        """Standard two-digit-prefix per-file copy lines must match."""
        assert _COPY_LINE_RE.match(line), f"Expected match for: {line!r}"

    def test_matches_single_digit_thread(self):
        """Thread index ``[1]`` (no leading zero) must still match."""
        assert _COPY_LINE_RE.match(
            "[1] NT: Copying /var/lib/mysql/db1/t1.ibd to /backup/t1.ibd\n"
        )

    def test_matches_triple_digit_thread(self):
        """Thread index ``[100]`` (three digits) must match — high-parallelism jobs."""
        assert _COPY_LINE_RE.match(
            "[100] NT: Copying /var/lib/mysql/db1/t1.ibd to /backup/t1.ibd\n"
        )

    def test_matches_tab_separator_after_thread(self):
        r"""Tab between ``[N]`` and ``NT:`` must match; regex allows ``\s`` which includes tab."""
        assert _COPY_LINE_RE.match(
            "[01]\tNT: Copying /var/lib/mysql/db1/t1.ibd to /backup/t1.ibd\n"
        )

    def test_matches_zero_percent_progress(self):
        """0% progress line (first update) must be filtered."""
        assert _COPY_LINE_RE.match("[01] ...db1/t1.ibd: 0% copied\n")

    def test_matches_single_digit_percent(self):
        """Single-digit percentage (e.g. 1%) must be filtered."""
        assert _COPY_LINE_RE.match("[01] ...db1/t1.ibd: 1% copied\n")


class TestCopyLineRegexPassesThroughLines:
    """Lines that MUST pass through regardless of the ``xtrabackup_quiet`` setting."""

    @pytest.mark.parametrize(
        "line",
        [
            # Error lines — even those mentioning "Copying"
            "[01] Error: InnoDB: Cannot copy file\n",
            "[01] Error: Copying failed fatally\n",
            "[01] FATAL: failed during copy phase\n",
            # Summary / completion lines (no ``[N]`` prefix)
            "xtrabackup: completed OK!\n",
            "xtrabackup: Transaction log of lsn (12345) to (67890) was copied.\n",
            # Warning lines
            "[01] Warning: Got error 32 when reading table\n",
            # Galera lines
            "[01] WSREP_SST: Galera node synced\n",
            # Wrong extension (.frm, .MYD — not .ibd)
            "[01] NT: Copying /var/lib/mysql/db1/t1.frm\n",
            "[01] NT: Copying /var/lib/mysql/db1/t1.MYD\n",
            # "Copying" without an .ibd file path
            "[01] NT: Copying done\n",
            # Progress with wrong suffix
            "[01] ...table1.ibd: resumed\n",
            "[01] ...table1.ibd: 45% verified\n",
            # Empty / blank
            "\n",
            "",
            # Mid-line match attempt — regex is anchored, so this must not fire
            "prefix [01] NT: Copying /var/lib/mysql/db1/t1.ibd\n",
            # Error text appended after .ibd — the false-positive the end anchor guards against
            "[01] NT: Copying /var/lib/mysql/db1/t1.ibd failed: disk full\n",
            "[01] NT: Finished copying /var/lib/mysql/db1/t1.ibd error: something\n",
        ],
    )
    def test_does_not_match(self, line: str):
        """Non-copy lines must never match the filter regex."""
        assert not _COPY_LINE_RE.match(line), f"Unexpected match for: {line!r}"

    def test_case_sensitive_copying(self):
        """``COPYING`` (uppercase) must not match — regex is case-sensitive by design."""
        assert not _COPY_LINE_RE.match("[01] NT: COPYING /var/lib/mysql/db1/t1.ibd\n")

    def test_case_sensitive_finished_copying(self):
        """``FINISHED COPYING`` must not match."""
        assert not _COPY_LINE_RE.match(
            "[01] NT: FINISHED COPYING /var/lib/mysql/db1/t1.ibd\n"
        )

    def test_empty_thread_brackets_do_not_match(self):
        """``[]`` (no digits) must not match; thread index is required."""
        assert not _COPY_LINE_RE.match(
            "[] NT: Copying /var/lib/mysql/db1/t1.ibd to /backup/t1.ibd\n"
        )

    def test_non_numeric_thread_does_not_match(self):
        """``[abc]`` (non-numeric thread) must not match."""
        assert not _COPY_LINE_RE.match(
            "[abc] NT: Copying /var/lib/mysql/db1/t1.ibd to /backup/t1.ibd\n"
        )

    def test_ibd_in_body_text_without_nt_prefix_does_not_match(self):
        """``[N] reading ibdata1.ibd ...`` — no ``NT:`` or ``...`` prefix must not match.

        Prevents false-positive filtering if xtrabackup ever logs a line that
        mentions an .ibd filename in a non-copy context (e.g. tablespace scan).
        """
        assert not _COPY_LINE_RE.match("[01] reading ibdata1.ibd file\n")
