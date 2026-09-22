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

"""Test how a service's role is read off its probe record.

``om.service.role`` was documented as ``mongod`` / ``mongos`` / ``config`` /
``arbiter`` and written as ``NULL`` on every upsert. These pin the table
:func:`classify_role` implements, in the order that matters: an arbiter is itself a
``mongod`` process, so it has to be recognised before the ``mongod`` fallback claims
it, and a router's own ``mongos`` line must not fall through to that fallback either.
"""

from app.sep.apps.om_inventory.service import classify_role


def record(
    *,
    is_arbiter: bool | None = None,
    msg: str | None = None,
    program: str | None = "mongod",
    argv: str = "/usr/bin/mongod --config /etc/mongod.conf",
    running: bool = True,
    cluster_role: str | None = None,
) -> dict:
    """Build a probe record trimmed to the fields the classifier reads.

    :param is_arbiter: ``hello.arbiterOnly``, as the payload summarises it.
    :param msg: ``hello.msg``, ``"isdbgrid"`` on a mongos.
    :param program: The server process's program, or ``None`` when none was found.
    :param argv: The server process's full command line.
    :param running: Whether a server process was found at all.
    :param cluster_role: ``sharding.clusterRole`` as ``getCmdLineOpts`` resolves it -
        how a real config server actually declares itself.
    :return: The record.
    """
    return {
        "database": {
            "is_arbiter": is_arbiter,
            "msg": msg,
            "raw": {
                "cmd_line_opts": {
                    "parsed": {"sharding": {"clusterRole": cluster_role}}
                    if cluster_role
                    else {}
                }
            },
        },
        "process": {
            "running": running,
            "program": program if running else None,
            "argv": argv if running else None,
        },
    }


class TestClassifyRole:
    """Pin the precedence table :func:`classify_role` implements."""

    def test_an_arbiter_is_not_classified_as_a_plain_mongod(self) -> None:
        """Classify an arbiter as arbiter even though it is itself a mongod process."""
        assert classify_role(record(is_arbiter=True)) == "arbiter"

    def test_a_router_is_mongos_by_its_own_program(self) -> None:
        """Classify a router as mongos when its own process says so."""
        assert (
            classify_role(record(program="mongos", argv="/usr/bin/mongos")) == "mongos"
        )

    def test_a_router_is_mongos_by_hello_when_the_program_cannot_say(self) -> None:
        """Catch a mongos via ``hello.msg`` when its process facts came back empty."""
        assert (
            classify_role(record(msg="isdbgrid", program=None, running=False))
            == "mongos"
        )

    def test_a_config_server_is_read_from_get_cmd_line_opts(self) -> None:
        """Read a config server's role from ``getCmdLineOpts`` rather than argv.

        Measured against this workspace's sharded sandbox, where every config server
        runs as ``mongod --config /etc/mongod-node.conf`` and reports
        ``parsed.sharding.clusterRole == "configsvr"``. Reading argv alone labelled
        all three of them ``mongod``.
        """
        assert (
            classify_role(
                record(
                    cluster_role="configsvr",
                    argv="/usr/bin/mongod --config /etc/mongod-node.conf",
                )
            )
            == "config"
        )

    def test_a_config_server_started_with_the_flag_is_still_config(self) -> None:
        """Fall back to argv's ``--configsvr`` flag when database facts never came back."""
        assert (
            classify_role(
                record(argv="/usr/bin/mongod --configsvr --config /etc/mongod.conf")
            )
            == "config"
        )

    def test_a_shard_member_is_not_a_config_server(self) -> None:
        """Treat a shardsvr's ``clusterRole`` as mongod, not as a config server."""
        assert classify_role(record(cluster_role="shardsvr")) == "mongod"

    def test_an_ordinary_member_is_mongod(self) -> None:
        """Classify a running server process as mongod when none of the above match."""
        assert classify_role(record()) == "mongod"

    def test_no_server_process_found_classifies_as_nothing(self) -> None:
        """Keep a previously good role rather than blanking it on absence."""
        assert classify_role(record(program=None, running=False)) is None
