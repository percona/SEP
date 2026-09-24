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

"""Cover the payload's compression defaults, which belong to the binary not the type.

Which ``--compress`` algorithms exist is a property of the backup binary: only
``xtrabackup`` runs zstd and lz4, while ``innobackupex`` and ``mariadb-backup`` run
quicklz. A blank algorithm therefore cannot be resolved from the backup type alone,
and the form deliberately leaves a blank algorithm alone — so the payload is the
only place a stored blank can be resolved against the binary that will run.

The expectations derive from ``resolve_xtrabackup_compression``, the dispatch-side
resolver, so the two sides cannot drift; the algorithm names themselves are typed
out once, in ``test_forms.py``, where that resolver is pinned.

The resolution happens in ``BaseBackup.__init__``, which the synthetic-instance
harness cannot drive, so the initializer is lifted to module level and handed a
plain object as ``self``.
"""

import logging
import pathlib

import pytest

from app.extensions.apps.mysql_backups.forms import (
    ALLOWED_XTRABACKUP_BIN_COMPRESSIONS,
    resolve_xtrabackup_compression,
    XTRABACKUP_BIN_DEFAULT,
)
from app.extensions.apps.mysql_backups.models import XtraBackupTool
from tests.app.extensions.apps.mysql_backups.payload_harness import (
    load_function,
    payload_instance,
    payload_method,
    seeded_instance,
)

_BINARIES = tuple(binary.value for binary in ALLOWED_XTRABACKUP_BIN_COMPRESSIONS)

#: The payload's own per-binary rows, lifted once: every extraction re-parses the
#: payload, and nothing here mutates what it returns.
_SUPPORTED_COMPRESSION = load_function("supported_compression")

#: A binary the payload has never heard of, to pin the unrecognized-name branch.
_UNKNOWN_BINARY = "xb-next"

#: Every algorithm any binary accepts, so an unsupported pairing is the complement
#: of a binary's own row rather than a second hand-written list.
_ALL_ALGORITHMS = {
    algorithm
    for allowed in ALLOWED_XTRABACKUP_BIN_COMPRESSIONS.values()
    for algorithm in allowed
}


def _initialized(**server_data: object) -> object:
    """Return an object carrying what the payload's initializer resolves from a config.

    :param server_data: The dispatched config keys the initializer reads, typed
        ``object`` because a dispatched config mixes booleans, paths and names.
    :return: The populated stand-in for a backup instance.
    """
    init = payload_method(
        "BaseBackup",
        "__init__",
        extra_namespace={"supported_compression": _SUPPORTED_COMPRESSION},
    )
    instance = type("_Instance", (), {})()
    init(instance, dict(server_data), "X", logging.getLogger("payload-test"))
    return instance


def _check_config_for(
    cnf: pathlib.Path, **attributes: object
) -> tuple[object, type[Exception]]:
    """Return a guard-carrying instance pointed at a readable option file.

    The pairing check shares its call site with the defaults-file guard, so the
    file has to be readable for a compression failure to be the one raised.

    :param cnf: The readable option file, from the ``readable_cnf`` fixture.
    :param attributes: Instance attributes the check reads, typed ``object``
        because the seeded state mixes booleans and names.
    :return: The instance and the payload's own ``BackupError``.
    """
    return seeded_instance(("_check_config",), defaults_cnf_file=str(cnf), **attributes)


class TestBlankAlgorithmResolvesPerBinary:
    """Assert a blank algorithm resolves to one the selected binary can actually run.

    The binary is read in the base initializer, which these tests lift on its own:
    moving that read back into the subclass, where it used to live and where it
    would run after the resolution, leaves every case here unresolvable.
    """

    @pytest.mark.parametrize("binary", ALLOWED_XTRABACKUP_BIN_COMPRESSIONS)
    def test_resolved_default_matches_the_dispatch_resolver(
        self, binary: XtraBackupTool
    ) -> None:
        """Assert the payload resolves a blank exactly as dispatch resolves it."""
        instance = _initialized(XTRABACKUP_BIN_CMD=binary.value)
        assert instance.compression_algorithm == resolve_xtrabackup_compression(binary)

    def test_blank_binary_resolves_like_the_execution_default(self) -> None:
        """Assert a config carrying no binary resolves both the binary and its algorithm."""
        instance = _initialized()
        assert instance.xtrabackup_bin_cmd == XTRABACKUP_BIN_DEFAULT.value
        assert instance.compression_algorithm == resolve_xtrabackup_compression(None)

    def test_unknown_binary_follows_the_command_builder(self) -> None:
        """Assert an unrecognized binary resolves as the binary it will actually invoke.

        ``_run_backup_cmd`` maps anything it does not recognize onto innobackupex, so
        the algorithm list follows the same mapping or validation and execution
        disagree. Only the binary name is typed out, because no enum member exists
        for a name the form cannot produce.
        """
        instance = _initialized(XTRABACKUP_BIN_CMD=_UNKNOWN_BINARY)
        assert instance.compression_algorithm == resolve_xtrabackup_compression(
            XtraBackupTool.INNOBACKUPEX
        )

    def test_explicit_algorithm_is_untouched(self) -> None:
        """Assert an algorithm the config names is never overridden by the default."""
        instance = _initialized(
            XTRABACKUP_BIN_CMD="xtrabackup", COMPRESSION_ALGORITHM="lz4"
        )
        assert instance.compression_algorithm == "lz4"

    def test_empty_algorithm_falls_back_to_the_default(self) -> None:
        """Assert an empty algorithm in a stored config resolves rather than dispatching.

        An empty string names no compressor, so treating it as a set value would
        hand the binary a flag it cannot parse.
        """
        instance = _initialized(
            XTRABACKUP_BIN_CMD="innobackupex", COMPRESSION_ALGORITHM=""
        )
        assert instance.compression_algorithm == resolve_xtrabackup_compression(
            XtraBackupTool.INNOBACKUPEX
        )

    @pytest.mark.parametrize("binary", [*_BINARIES, _UNKNOWN_BINARY])
    def test_resolved_default_maps_to_a_compressor(self, binary: str) -> None:
        """Assert every resolved default has an extension and a tool to run it."""
        inst, _, _ = payload_instance(("get_compression_ext", "get_compression_tool"))
        inst.compression_algorithm = _initialized(
            XTRABACKUP_BIN_CMD=binary
        ).compression_algorithm
        assert inst.get_compression_ext()
        assert inst.get_compression_tool()


class TestUnsupportedAlgorithmRejected:
    """Assert the payload rejects a pairing the binary cannot run, naming the binary."""

    @pytest.mark.parametrize(
        ("binary", "algorithm"),
        [
            (binary.value, algorithm.value)
            for binary, allowed in ALLOWED_XTRABACKUP_BIN_COMPRESSIONS.items()
            for algorithm in allowed
        ],
    )
    def test_supported_pairing_passes(
        self, readable_cnf: pathlib.Path, binary: str, algorithm: str
    ) -> None:
        """Assert every pairing the matrix allows is accepted."""
        inst, _ = _check_config_for(
            readable_cnf, xtrabackup_bin_cmd=binary, compression_algorithm=algorithm
        )
        assert inst._check_config() is None

    @pytest.mark.parametrize(
        ("binary", "algorithm"),
        [
            (binary.value, algorithm.value)
            for binary, allowed in ALLOWED_XTRABACKUP_BIN_COMPRESSIONS.items()
            for algorithm in sorted(_ALL_ALGORITHMS - set(allowed))
        ],
    )
    def test_unsupported_pairing_names_the_binary(
        self, readable_cnf: pathlib.Path, binary: str, algorithm: str
    ) -> None:
        """Assert the failure names the binary, not the backup type it was keyed on."""
        inst, backup_error = _check_config_for(
            readable_cnf, xtrabackup_bin_cmd=binary, compression_algorithm=algorithm
        )
        with pytest.raises(backup_error) as excinfo:
            inst._check_config()
        assert binary in str(excinfo.value)

    @pytest.mark.parametrize("binary", _BINARIES)
    def test_gzip_is_rejected_by_every_binary(
        self, readable_cnf: pathlib.Path, binary: str
    ) -> None:
        """Assert gzip is refused, the algorithm the type-keyed list used to offer.

        No xtrabackup binary compresses with gzip, which is why the extension and
        tool tables no longer carry a row for it.
        """
        inst, backup_error = _check_config_for(
            readable_cnf, xtrabackup_bin_cmd=binary, compression_algorithm="gzip"
        )
        with pytest.raises(backup_error):
            inst._check_config()

    def test_compression_off_skips_the_check(self, readable_cnf: pathlib.Path) -> None:
        """Assert the check stays inert when nothing will be compressed."""
        inst, _ = _check_config_for(
            readable_cnf,
            compress=False,
            xtrabackup_bin_cmd="innobackupex",
            compression_algorithm="zstd",
        )
        assert inst._check_config() is None


class TestPayloadMatrixMatchesForm:
    """Pin the payload's per-binary lists to the matrix the create form gates on.

    Content and preference are asserted apart: the rows hold the same algorithms,
    and each row leads with the one a blank algorithm resolves to. A single ordered
    comparison would fail on both counts at once and say neither.
    """

    @pytest.mark.parametrize("binary", ALLOWED_XTRABACKUP_BIN_COMPRESSIONS)
    def test_rows_match_the_form(self, binary: XtraBackupTool) -> None:
        """Assert each binary allows exactly the algorithms the form allows it."""
        expected = {
            algorithm.value for algorithm in ALLOWED_XTRABACKUP_BIN_COMPRESSIONS[binary]
        }
        assert set(_SUPPORTED_COMPRESSION(binary.value)) == expected

    @pytest.mark.parametrize("binary", ALLOWED_XTRABACKUP_BIN_COMPRESSIONS)
    def test_the_preferred_algorithm_leads_its_row(
        self, binary: XtraBackupTool
    ) -> None:
        """Assert the first entry is the one a blank algorithm resolves to."""
        assert _SUPPORTED_COMPRESSION(binary.value)[0] == (
            resolve_xtrabackup_compression(binary)
        )
