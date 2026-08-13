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

"""Tests for the ``scripts/check_nomad_payload_size.py`` CLI."""

import importlib.util
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "check_nomad_payload_size.py"

_spec = importlib.util.spec_from_file_location("check_nomad_payload_size", _SCRIPT_PATH)
assert _spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
check_nomad_payload_size = importlib.util.module_from_spec(_spec)
sys.modules["check_nomad_payload_size"] = check_nomad_payload_size
_spec.loader.exec_module(check_nomad_payload_size)


VERBOSE_SCRIPT = '''\
"""A verbose module that minifies to something much smaller."""


def hello(name: str = "world") -> str:
    """Return a friendly greeting."""
    return f"hello, {name}"
'''

INVALID_SCRIPT = "def oops(:\n"


def _write(tmp_path, name, text):
    """Write ``text`` to ``tmp_path/name`` and return the path.

    :param tmp_path: pytest's per-test temporary directory.
    :type tmp_path: pathlib.Path
    :param name: The filename to create under ``tmp_path``.
    :type name: str
    :param text: UTF-8 contents to write.
    :type text: str
    :return: The newly-written path.
    :rtype: pathlib.Path
    """
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_check_payload_uses_minified_text_for_size(tmp_path, monkeypatch):
    """``check_payload`` gzip-compresses the minified source, not the original text."""
    path = _write(tmp_path, "verbose.py", VERBOSE_SCRIPT)
    seen = {}
    real_minify = check_nomad_payload_size.minify

    def spy_minify(src, **kwargs):
        out = real_minify(src, **kwargs)
        seen["minified"] = out
        return out

    monkeypatch.setattr(check_nomad_payload_size, "minify", spy_minify)
    monkeypatch.setattr(check_nomad_payload_size, "NOMAD_PAYLOAD_SIZE_LIMIT", 0)
    _, size = check_nomad_payload_size.check_payload(str(path))
    assert len(seen["minified"]) < len(VERBOSE_SCRIPT)
    assert size > 0


def test_check_payload_falls_back_on_syntax_error(tmp_path, monkeypatch):
    """``check_payload`` ignores ``SyntaxError`` from ``minify`` and uses raw source."""
    path = _write(tmp_path, "broken.py", INVALID_SCRIPT)

    def raise_syntax(src, **kwargs):
        raise SyntaxError("boom")

    monkeypatch.setattr(check_nomad_payload_size, "minify", raise_syntax)
    monkeypatch.setattr(check_nomad_payload_size, "NOMAD_PAYLOAD_SIZE_LIMIT", 0)
    result = check_nomad_payload_size.check_payload(str(path))
    assert result is not None
    assert result[0] == str(path)
    assert result[1] > 0


def test_main_reports_oversized_file_and_returns_one(tmp_path, monkeypatch, capsys):
    """``main`` exits 1 and prints path, size, and limit when a file exceeds the limit."""
    path = _write(tmp_path, "verbose.py", VERBOSE_SCRIPT)
    monkeypatch.setattr(check_nomad_payload_size, "NOMAD_PAYLOAD_SIZE_LIMIT", 1)
    monkeypatch.setattr(sys, "argv", ["check_nomad_payload_size.py", str(path)])
    assert check_nomad_payload_size.main() == 1
    out = capsys.readouterr().out
    assert "exceed Nomad" in out
    assert str(path) in out
    assert "limit: 1" in out


def test_main_returns_zero_when_within_limit(tmp_path, monkeypatch, capsys):
    """``main`` exits 0 and prints nothing when all files are within the limit."""
    path = _write(tmp_path, "verbose.py", VERBOSE_SCRIPT)
    monkeypatch.setattr(sys, "argv", ["check_nomad_payload_size.py", str(path)])
    assert check_nomad_payload_size.main() == 0
    assert capsys.readouterr().out == ""


def test_report_prints_size_headroom_and_returns_zero(tmp_path, monkeypatch, capsys):
    """``--report`` prints size, limit, and headroom and always exits 0."""
    path = _write(tmp_path, "verbose.py", VERBOSE_SCRIPT)
    limit = 10_000
    monkeypatch.setattr(check_nomad_payload_size, "NOMAD_PAYLOAD_SIZE_LIMIT", limit)
    size = check_nomad_payload_size.payload_size(str(path))
    headroom = limit - size
    assert check_nomad_payload_size.main(["--report", str(path)]) == 0
    out = capsys.readouterr().out.strip()
    assert out == (f"{path}: {size:,} / {limit:,} bytes ({headroom:,} bytes headroom)")


def test_report_returns_zero_when_over_limit(tmp_path, monkeypatch, capsys):
    """``--report`` exits 0 even when a payload exceeds the limit."""
    path = _write(tmp_path, "verbose.py", VERBOSE_SCRIPT)
    monkeypatch.setattr(check_nomad_payload_size, "NOMAD_PAYLOAD_SIZE_LIMIT", 1)
    size = check_nomad_payload_size.payload_size(str(path))
    over = size - 1
    assert check_nomad_payload_size.main(["--report", str(path)]) == 0
    out = capsys.readouterr().out.strip()
    assert "OVER LIMIT" in out
    assert f"{over:,} bytes OVER LIMIT" in out
    assert str(path) in out


def test_report_prints_one_line_per_path(tmp_path, monkeypatch, capsys):
    """``--report`` prints one line per path when multiple paths are given."""
    path_a = _write(tmp_path, "a.py", VERBOSE_SCRIPT)
    path_b = _write(tmp_path, "b.py", VERBOSE_SCRIPT)
    limit = 10_000
    monkeypatch.setattr(check_nomad_payload_size, "NOMAD_PAYLOAD_SIZE_LIMIT", limit)
    size = check_nomad_payload_size.payload_size(str(path_a))
    headroom = limit - size
    line = f"{path_a}: {size:,} / {limit:,} bytes ({headroom:,} bytes headroom)"
    assert check_nomad_payload_size.main(["--report", str(path_a), str(path_b)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == len((path_a, path_b))
    assert lines[0] == line
    assert lines[1] == line.replace(str(path_a), str(path_b))
