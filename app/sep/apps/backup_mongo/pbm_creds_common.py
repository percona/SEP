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

"""Define the single canonical PBM credential-resolution preamble.

The nine ``backup_mongo`` payload scripts are shipped to executors by ``file://``
reference and read directly from disk, so they cannot import a shared module at
execution time. Instead, the block between :data:`PREAMBLE_BEGIN` and
:data:`PREAMBLE_END` below is the one canonical definition of the PBM
credential-resolution helpers, materialized verbatim into each payload's marked
region by ``scripts/gen_pbm_payloads.py`` and guarded in-sync (and behaviorally)
by ``tests/app/sep/apps/backup_mongo/test_pbm_payload_preamble.py``.

A hardening fix to credential handling therefore lands here once and propagates
to all nine payloads via the regen step, instead of drifting across nine copies.
The two ``_creds_path`` shapes are both served here: :func:`_creds_path` reads the
``NOMAD_META_CONFIG`` environment variable (the backup/restore standalone legs),
and :func:`_creds_path_from_config` reads an already-parsed config dict (the
restore legs that load ``script_config``). The ``config_source`` word ("backup"
or "restore") is passed by the payload's call site so each script emits exactly
the stderr message it does today.

This module is deliberately importable and linted (unlike the payloads, which are
excluded from ruff), so the helpers are exercised directly by test. It uses only
the standard-library ``open`` / ``os`` / ``sys`` and ``yaml`` that every payload
already imports, so the extracted region drops into a payload unchanged.
"""

import os
import sys
from pathlib import Path

import yaml

PREAMBLE_BEGIN = "# --- BEGIN GENERATED PBM CREDS PREAMBLE ---"
PREAMBLE_END = "# --- END GENERATED PBM CREDS PREAMBLE ---"


# --- BEGIN GENERATED PBM CREDS PREAMBLE ---
def _creds_path(config_source: str) -> str:
    """Resolve the MongoDB URI credentials path from ``NOMAD_META_CONFIG``.

    :param config_source: The config surface named in the error message, either
        ``"backup"`` or ``"restore"``.
    :return: The credentials-file path (from the config or the ``$HOME`` fallback).
    """
    config_yaml = os.environ.get("NOMAD_META_CONFIG")
    if config_yaml:
        try:
            config = yaml.safe_load(config_yaml)
            if config:
                path = config.get("credentials_path")
                if path:
                    return path
        except yaml.YAMLError as err:
            print(
                f"Failed to parse NOMAD_META_CONFIG as YAML: {err}. Falling back to HOME-based credentials path.",
                file=sys.stderr,
            )
    envhome = os.environ.get("HOME")
    if not envhome:
        print(
            f"PBM credentials path not set (credentials_path in {config_source} config) and HOME is unset",
            file=sys.stderr,
        )
        sys.exit(1)
    return f"{envhome}/.mongodb_uri"


def _creds_path_from_config(config: dict | None, config_source: str = "restore") -> str:
    """Resolve the MongoDB URI credentials path from an already-parsed config dict.

    :param config: The parsed restore/backup config dict, or ``None`` when absent.
    :param config_source: The config surface named in the error message, either
        ``"backup"`` or ``"restore"``.
    :return: The credentials-file path (from the config or the ``$HOME`` fallback).
    """
    if config:
        path = config.get("credentials_path")
        if path:
            return path
    envhome = os.environ.get("HOME")
    if not envhome:
        print(
            f"PBM credentials path not set (credentials_path in {config_source} config) and HOME is unset",
            file=sys.stderr,
        )
        sys.exit(1)
    return f"{envhome}/.mongodb_uri"


def pbm_creds(creds_path: str) -> str:
    """Read the MongoDB URI from ``creds_path``, exiting 1 on any read failure.

    :param creds_path: The resolved credentials-file path to read.
    :return: The stripped MongoDB URI read from the file.
    """
    try:
        with open(creds_path, encoding="utf-8") as fpt:
            return fpt.read().strip()
    except FileNotFoundError as err:
        print(f"Credentials file not found: {creds_path}: {err}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as err:
        print(
            f"Permission denied reading credentials file {creds_path}: {err}",
            file=sys.stderr,
        )
        sys.exit(1)
    except OSError as err:
        print(f"Error reading credentials file {creds_path}: {err}", file=sys.stderr)
        sys.exit(1)
    except Exception as err:
        print(f"Error reading credentials file {creds_path}: {err}", file=sys.stderr)
        sys.exit(1)


# --- END GENERATED PBM CREDS PREAMBLE ---


def preamble_source() -> str:
    """Return the canonical generated-preamble region text.

    Extract the lines strictly between :data:`PREAMBLE_BEGIN` and
    :data:`PREAMBLE_END` (both exclusive) from this module's own source, so the
    codegen step and the in-sync guard share one definition of "the block".

    :return: The preamble body text, stripped of its leading/trailing blank lines.
    :raises ValueError: When either marker is missing from the module source.
    """
    lines = Path(__file__).read_text(encoding="utf-8").splitlines()
    try:
        begin = lines.index(PREAMBLE_BEGIN)
        end = lines.index(PREAMBLE_END, begin + 1)
    except ValueError as exc:
        raise ValueError(
            "pbm_creds_common.py is missing a PBM CREDS PREAMBLE marker line"
        ) from exc
    return "\n".join(lines[begin + 1 : end]).strip("\n")
