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

"""Share the PBM payload codegen loading and region-extraction test helpers.

Both the creds-preamble and the textfile-collector region test modules load the
``scripts/gen_pbm_payloads.py`` generator by path and slice a payload's marked
region out of its source. Hosting that boilerplate here keeps the two modules
from drifting and gives every payload-region test one loader and one extractor.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "gen_pbm_payloads.py"


def _load_generator() -> ModuleType:
    """Load ``scripts/gen_pbm_payloads.py`` as an importable module by path.

    The generator is a CLI script (not on the package path), so it is loaded from
    its file location and registered under its own name once for all callers.

    :return: The loaded ``gen_pbm_payloads`` module.
    """
    spec = importlib.util.spec_from_file_location("gen_pbm_payloads", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_pbm_payloads"] = module
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()


def payloads_with(begin_marker: str) -> list[Path]:
    """Return the payloads that opt into the region delimited by ``begin_marker``.

    :param begin_marker: The BEGIN marker line a payload must carry to opt in.
    :return: The opted-in payload paths under the real backup_mongo app.
    """
    return GEN.find_payloads(GEN.DEFAULT_SEARCH_ROOT, begin_marker)


def region_between(text: str, begin_marker: str, end_marker: str) -> str:
    """Return the lines of ``text`` strictly between the two marker lines.

    :param text: The payload source to slice.
    :param begin_marker: The BEGIN marker line delimiting the region.
    :param end_marker: The END marker line delimiting the region.
    :return: The region body, stripped of its leading/trailing blank lines.
    """
    lines = text.split("\n")
    begin = lines.index(begin_marker)
    end = lines.index(end_marker, begin + 1)
    return "\n".join(lines[begin + 1 : end]).strip("\n")


def assignment_line(text: str, token: str) -> str:
    """Return the first stripped assignment line of ``text`` mentioning ``token``.

    :param text: The payload source to scan.
    :param token: The identifier the assignment line must contain.
    :return: The stripped assignment line.
    :raises AssertionError: When no assignment mentioning ``token`` is found.
    """
    for line in text.splitlines():
        if token in line and "=" in line:
            return line.strip()
    raise AssertionError(f"no {token} assignment found")
