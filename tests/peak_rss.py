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

"""Report each pytest process's peak resident memory, on request.

Setting ``PYTEST_PEAK_RSS_FILE`` to a file path makes every process of the run,
each xdist worker and the controller, append one JSON line to that file when its
session finishes::

    {"worker": "gw0", "peak_rss_mb": 658}

The controller then prints every line and the median over the workers, which
is the figure to compare between runs. The controller's own peak is excluded
from the median because it collects and runs nothing under xdist.

Lines are appended, never truncated, so point each run at a fresh path; a
reused file mixes runs into one median. The file's directory must already
exist, and a write that fails raises rather than dropping the figure.

The peak is ``ru_maxrss``, a high-water mark: freed heap is reused rather than
returned to the OS, so end-of-run RSS understates what a worker needed.

Only the standard library is imported, so the root ``conftest.py`` can load
this before any application module.
"""

import json
import os
import resource
import statistics
import sys
from pathlib import Path
from typing import Any

PEAK_RSS_FILE_ENV = "PYTEST_PEAK_RSS_FILE"
CONTROLLER = "controller"


def _peak_rss_mb() -> int:
    """Return this process's peak resident set size in whole megabytes.

    ``ru_maxrss`` is reported in KiB on Linux and in bytes on macOS.
    """
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return peak // divisor


def _report_path() -> Path | None:
    """Return the requested report file, or ``None`` when none was requested."""
    path = os.environ.get(PEAK_RSS_FILE_ENV)
    return Path(path) if path else None


def record_peak_rss(config: Any) -> None:
    """Append this process's peak RSS to the report file, when one is requested.

    :param config: The pytest config; an xdist worker's carries ``workerinput``.
    """
    path = _report_path()
    if path is None:
        return
    workerinput = getattr(config, "workerinput", None)
    worker = workerinput["workerid"] if workerinput else CONTROLLER
    line = json.dumps({"worker": worker, "peak_rss_mb": _peak_rss_mb()})
    with path.open("a", encoding="utf-8") as report:
        report.write(line + "\n")


def peak_rss_summary() -> list[str]:
    """Return the report file's lines as text, ending with the worker median.

    :return: One line per process plus the median line, or an empty list when
        no report was requested.
    """
    path = _report_path()
    if path is None:
        return []
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    lines = [f"{record['worker']}: {record['peak_rss_mb']} MB" for record in records]
    worker_peaks = [
        record["peak_rss_mb"] for record in records if record["worker"] != CONTROLLER
    ]
    if worker_peaks:
        median = round(statistics.median(worker_peaks))
        lines.append(
            f"median worker peak RSS: {median} MB over {len(worker_peaks)} worker(s)"
        )
    else:
        lines.append("median worker peak RSS: n/a (no xdist workers)")
    return lines
