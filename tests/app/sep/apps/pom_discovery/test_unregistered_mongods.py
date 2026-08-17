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

"""Test the payload's report of mongods PMM has no service for.

Arbiters are why this is ordinary rather than exotic. An arbiter holds no data and
therefore no user documents, so SCRAM cannot authenticate and ``pmm-admin add
mongodb`` fails for it -- meaning **any** estate with arbiters and authentication
enabled has databases PMM does not know about. Three of this sandbox's nodes are in
exactly that state.

They are reported on the *host* rather than as service rows: there is no service id
to key a row on, and inventing an identity would commit to a shape before anything
needs it. What matters is that they are not silently dropped, because then the estate
view gets to call a host empty while a mongod runs on it.

The port is the join. Getting it wrong in either direction is a real failure: miss a
port and a registered service is reported as a stranger; invent one and a genuine
stranger disappears.
"""

import pytest

from app.sep.apps.pom_discovery.payload.probe import (
    find_unregistered,
    parse_config_path,
    parse_port,
)

CONFIG_PATH = "/etc/mongod-node.conf"
SHARD_PORT = 27018
DEFAULT_PORT = 27017


class TestParseConfigPath:
    """Assert the configuration file is found however it was passed."""

    @pytest.mark.parametrize(
        "argv",
        [
            f"/usr/bin/mongod --config {CONFIG_PATH}",
            f"/usr/bin/mongod -f {CONFIG_PATH}",
            f"/usr/bin/mongod --config={CONFIG_PATH}",
        ],
        ids=["--config", "-f", "--config="],
    )
    def test_reads_the_path(self, argv: str) -> None:
        """All three spellings appear in the wild.

        :param argv: The command line to read.
        """
        assert parse_config_path(argv) == CONFIG_PATH

    def test_absent_when_started_without_one(self) -> None:
        """A mongod started with flags alone has no config file."""
        assert parse_config_path("/usr/bin/mongod --port 27017 --dbpath /data") is None


class TestParsePort:
    """Assert the port is found on the command line or in the config file."""

    def test_prefers_the_command_line(self, tmp_path) -> None:
        """An explicit ``--port`` is what the process actually did.

        :param tmp_path: pytest's temporary directory.
        """
        config = tmp_path / "mongod.conf"
        config.write_text("net:\n  port: 27017\n")

        port = parse_port(f"/usr/bin/mongod --port {SHARD_PORT}", str(config))

        assert port == SHARD_PORT

    @pytest.mark.parametrize(
        "argv",
        ["/usr/bin/mongod --port 27018", "/usr/bin/mongod --port=27018"],
        ids=["space", "equals"],
    )
    def test_reads_either_command_line_spelling(self, argv: str) -> None:
        """``--port N`` and ``--port=N`` are both used.

        :param argv: The command line to read.
        """
        assert parse_port(argv, None) == SHARD_PORT

    def test_falls_back_to_the_config_file(self, tmp_path) -> None:
        """The sandbox starts every node with the port set in its config.

        An argv-only reading would find nothing on any of them, which would make
        every registered service look unregistered.

        :param tmp_path: pytest's temporary directory.
        """
        config = tmp_path / "mongod.conf"
        config.write_text(
            "storage:\n  dbPath: /var/lib/mongo\nnet:\n"
            f"  port: {SHARD_PORT}\n  bindIpAll: true\n"
        )

        assert parse_port("/usr/bin/mongod --config x", str(config)) == SHARD_PORT

    def test_ignores_a_trailing_comment(self, tmp_path) -> None:
        """Config files are hand-edited, and hand-edited files carry comments.

        :param tmp_path: pytest's temporary directory.
        """
        config = tmp_path / "mongod.conf"
        config.write_text("net:\n  port: 27018  # the shard port\n")

        assert parse_port("/usr/bin/mongod", str(config)) == SHARD_PORT

    def test_unreadable_config_is_not_fatal(self) -> None:
        """The payload must survive a config it cannot open, not abort the host."""
        assert parse_port("/usr/bin/mongod", "/nonexistent/mongod.conf") is None


def process(port: int | None, program: str = "mongod") -> dict:
    """Build one server process as the payload reports it.

    :param port: The port it listens on, or ``None`` when undetermined.
    :param program: ``mongod`` or ``mongos``.
    :return: The process mapping.
    """
    return {
        "program": program,
        "pid": 1,
        "port": port,
        "config_path": CONFIG_PATH,
        "argv": f"/usr/bin/{program} --config {CONFIG_PATH}",
    }


class TestFindUnregistered:
    """Assert which running servers are reported as strangers."""

    def test_a_registered_service_is_not_reported(self) -> None:
        """The ordinary case must stay quiet, or the list is noise."""
        found = find_unregistered(
            [process(DEFAULT_PORT)], [{"service": "db00", "port": DEFAULT_PORT}]
        )

        assert found == []

    def test_an_arbiter_with_no_target_is_reported(self) -> None:
        """The case this exists for: a mongod running where PMM has no service.

        The host is dispatched to and has no targets at all, so nothing accounts for
        the process.
        """
        found = find_unregistered([process(SHARD_PORT)], [])

        assert [entry["port"] for entry in found] == [SHARD_PORT]

    def test_a_second_mongod_beside_a_registered_one_is_reported(self) -> None:
        """One host, two databases, one of them known. Report the other."""
        found = find_unregistered(
            [process(DEFAULT_PORT), process(SHARD_PORT)],
            [{"service": "db00", "port": DEFAULT_PORT}],
        )

        assert [entry["port"] for entry in found] == [SHARD_PORT]

    def test_a_process_with_no_port_is_reported_rather_than_dropped(self) -> None:
        """An unidentifiable database is still a database.

        It cannot be matched to a target, and discarding it silently is exactly the
        dishonesty this list exists to prevent -- better a visible entry with a null
        port than a host that reads as empty.
        """
        found = find_unregistered(
            [process(None)], [{"service": "db00", "port": DEFAULT_PORT}]
        )

        assert [entry["port"] for entry in found] == [None]

    def test_a_target_without_a_port_registers_nothing(self) -> None:
        """A target carrying no port cannot account for any process.

        Treating ``None`` as a wildcard would hide every stranger on the host.
        """
        found = find_unregistered(
            [process(DEFAULT_PORT)], [{"service": "db00", "port": None}]
        )

        assert [entry["port"] for entry in found] == [DEFAULT_PORT]

    def test_a_mongos_is_matched_by_port_like_anything_else(self) -> None:
        """A router is a registered service too; it must not read as a stranger."""
        found = find_unregistered(
            [process(DEFAULT_PORT, program="mongos")],
            [{"service": "mongos00", "port": DEFAULT_PORT}],
        )

        assert found == []
