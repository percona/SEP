"""POM worker probe payload.

Runs on one executor host under the venv the ``run-python`` job template builds,
and collects, for every target named in the task config:

* the mongod process (pid, uptime, argv, config path) from ``ps``;
* the host's OS and kernel from ``/etc/os-release`` and ``uname``;
* the ``mongod`` binary version;
* a handful of database commands, when ``probe_database`` is set.

Prints **one JSON object per line to stdout** (NDJSON). That is the return channel:
the orchestrator streams the task log back and parses it line by line. It is used in
preference to the ``.sep-run-result.json`` file because that file is capped at 16 KB
and silently discarded above it, while the task-log chunk store has no total cap.

The config arrives as JSON in ``NOMAD_META_CONFIG``::

    {
      "targets": [{"service": "sc-cfg00", "host": "sc-cfg00", "port": 27019}, ...],
      "probe_database": true,
      "credentials_path": "/root/.mongodb_uri",   // absent = $HOME/.mongodb_uri
      "auth_source": "admin",
      "connect_timeout_ms": 5000
    }

Every target is attempted even when an earlier one fails: a per-target error becomes
an ``error`` field on that target's record. The process **exits 0 regardless**, so a
partial collection is still readable. A non-zero exit is reserved for "the payload
could not start at all", which is what the orchestrator reports as a dispatch
failure rather than a probe failure.

Beyond the standard library the only import is ``pymongo``, declared as the task's
pip requirements by the dispatcher. It is imported lazily so that a run with
``probe_database`` false works on a host without it.
"""

import json
import os
import platform
import subprocess
import sys
import time
from urllib.parse import quote_plus

DEFAULT_AUTH_SOURCE = "admin"
DEFAULT_CONNECT_TIMEOUT_MS = 5000
#: Basename of the node-side credentials file, under ``$HOME``. The same file the
#: PBM payloads and the MongoDB Status payload read.
DEFAULT_CREDENTIALS_BASENAME = ".mongodb_uri"
#: Bound on captured subprocess output. These commands emit a line or two; anything
#: larger means something unexpected ran and is not worth shipping through the log.
MAX_COMMAND_OUTPUT = 8192
#: Bound on how long any one shell probe may take.
COMMAND_TIMEOUT_SEC = 15
STATUS_OK = "ok"
STATUS_FAILED = "failed"


def load_config():
    """Return the task config parsed from ``NOMAD_META_CONFIG``.

    :return: The config mapping.
    """
    raw = os.environ.get("NOMAD_META_CONFIG")
    if not raw:
        print("NOMAD_META_CONFIG is not set", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(raw)
    except ValueError as err:
        print(f"NOMAD_META_CONFIG is not valid JSON: {err}", file=sys.stderr)
        sys.exit(1)


def run_command(args):
    """Run ``args`` and return its trimmed stdout, or ``None`` on any failure.

    Every shell probe here is best-effort: a missing binary, a non-zero exit, or a
    timeout yields ``None`` rather than aborting the record. The point is to collect
    what this host can tell us, not to insist it tells us everything.

    :param args: The argv list to execute.
    :return: The command's stdout stripped of surrounding whitespace, or ``None``.
    """
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout[:MAX_COMMAND_OUTPUT].strip() or None


def collect_os_facts():
    """Return the host's OS and kernel identity.

    :return: A mapping of OS facts; values are ``None`` where unavailable.
    """
    os_release = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            for line in handle:
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os_release[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
    return {
        "os_name": os_release.get("PRETTY_NAME") or os_release.get("NAME"),
        "os_id": os_release.get("ID"),
        "os_version_id": os_release.get("VERSION_ID"),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "hostname": platform.node(),
    }


#: The server programs a member may run. A shard, config server or arbiter runs
#: ``mongod``; a router runs ``mongos`` and no mongod at all, so looking only for
#: mongod reports every healthy router as down.
SERVER_PROGRAMS = ("mongod", "mongos")


def collect_process_facts():
    """Return facts about the running MongoDB server process, if there is one.

    Uses ``ps`` rather than reading ``/proc`` so the payload behaves the same on any
    host the executor runs on. ``etimes`` gives uptime in seconds directly.

    Looks for each of :data:`SERVER_PROGRAMS` in turn and reports which one was
    found in ``program``: a router runs ``mongos``, so a mongod-only check makes a
    healthy router indistinguishable from a dead node.

    :return: A mapping describing the server process; ``running`` is ``False`` and
        ``program`` is ``None`` when neither program was found.
    """
    for program in SERVER_PROGRAMS:
        output = run_command(["ps", "-o", "pid=,etimes=,args=", "-C", program])
        if output:
            break
    else:
        return {
            "running": False,
            "program": None,
            "pid": None,
            "uptime_sec": None,
            "argv": None,
        }
    # Take the first match; a host running several is out of scope for the worker.
    first = output.splitlines()[0].strip()
    parts = first.split(None, 2)
    if len(parts) < 3:
        return {
            "running": True,
            "program": program,
            "pid": None,
            "uptime_sec": None,
            "argv": first,
        }
    pid, etimes, argv = parts
    config_path = None
    tokens = argv.split()
    for index, token in enumerate(tokens):
        if token in ("-f", "--config") and index + 1 < len(tokens):
            config_path = tokens[index + 1]
            break
        if token.startswith("--config="):
            config_path = token.split("=", 1)[1]
            break
    return {
        "running": True,
        "program": program,
        "pid": int(pid) if pid.isdigit() else None,
        "uptime_sec": int(etimes) if etimes.isdigit() else None,
        "argv": argv,
        "config_path": config_path,
    }


def collect_binary_version(program=None):
    """Return the installed server binary's version string, or ``None``.

    Read from the binary rather than from the database so it is available even when
    the database is unreachable or ``probe_database`` is off -- an upgrade check
    needs the installed version, not the running one.

    Asks the program the member actually runs: a router's ``mongos --version``
    prints ``mongos version v…`` where mongod prints ``db version v…``, so both
    markers are accepted. Falls back to ``mongod`` when no process was found, since
    the binary is usually installed even when nothing is running.

    :param program: The server program detected by :func:`collect_process_facts`.
    :return: The version, e.g. ``7.0.39-21``, or ``None``.
    """
    output = run_command([program or "mongod", "--version"])
    if not output:
        return None
    first = output.splitlines()[0].strip()
    # "db version v7.0.14-8" / "mongos version v7.0.39-21" -> the bare version
    for marker in ("db version v", "mongos version v"):
        if marker in first:
            return first.split(marker, 1)[1].strip()
    return first


def read_userinfo(credentials_path):
    """Return percent-encoded ``user:pass@`` read from the node credentials file.

    The file is the same one the PBM and MongoDB Status payloads read. Its contents
    are accepted either as a full ``mongodb://user:pass@host:port`` URI or as the
    bare ``user:pass@host:port`` form the sandbox writes; only the credentials are
    taken, because host and port come from the config. A missing file is not an
    error -- an unauthenticated mongod is legitimate.

    :param credentials_path: Path to the credentials file, or ``None`` to skip.
    :return: The ``user:pass@`` prefix ready to splice into a URI, or ``""``.
    """
    if not credentials_path or not os.path.exists(credentials_path):
        return ""
    try:
        with open(credentials_path, encoding="utf-8") as handle:
            raw = handle.read().strip()
    except OSError as err:
        print(f"cannot read {credentials_path}: {err}", file=sys.stderr)
        return ""
    if not raw:
        return ""
    raw = raw.removeprefix("mongodb://")
    if "@" not in raw:
        return ""
    userinfo = raw.rsplit("@", 1)[0]
    if ":" not in userinfo:
        return ""
    user, _, password = userinfo.partition(":")
    return f"{quote_plus(user)}:{quote_plus(password)}@"


def build_uri(target, userinfo, auth_source, connect_timeout_ms):
    """Return the connection URI for one target.

    ``directConnection=true`` makes the commands report *this* node rather than
    whichever member the driver would otherwise elect to talk to; per-node facts are
    the point.

    :param target: The target mapping carrying ``host`` and ``port``.
    :param userinfo: The credentials prefix from :func:`read_userinfo`.
    :param auth_source: The database to authenticate against.
    :param connect_timeout_ms: Connect and server-selection timeout.
    :return: The MongoDB connection URI.
    """
    options = [
        "directConnection=true",
        f"connectTimeoutMS={connect_timeout_ms}",
        f"serverSelectionTimeoutMS={connect_timeout_ms}",
    ]
    if userinfo:
        options.append(f"authSource={auth_source}")
    return (
        f"mongodb://{userinfo}{target['host']}:{target['port']}/?{'&'.join(options)}"
    )


def collect_database_facts(target, userinfo, auth_source, connect_timeout_ms):
    """Return facts read from the database for one target.

    Each command is run independently so one failure does not lose the others --
    ``replSetGetStatus`` legitimately fails against a mongos or a standalone, and
    that must not discard the ``buildInfo`` that came back fine.

    :param target: The target mapping carrying ``host`` and ``port``.
    :param userinfo: The credentials prefix.
    :param auth_source: The database to authenticate against.
    :param connect_timeout_ms: Connect and server-selection timeout.
    :return: A mapping of database facts and per-command errors.
    """
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    facts = {}
    uri = build_uri(target, userinfo, auth_source, connect_timeout_ms)
    client = None
    try:
        client = MongoClient(uri)
        admin = client.admin
        for key, command in (
            ("build_info", "buildInfo"),
            ("hello", "hello"),
            ("cmd_line_opts", "getCmdLineOpts"),
            ("repl_set_status", "replSetGetStatus"),
        ):
            try:
                facts[key] = json.loads(json.dumps(admin.command(command), default=str))
            except PyMongoError as err:
                facts.setdefault("command_errors", {})[key] = str(err)
    except PyMongoError as err:
        facts["error"] = str(err)
    finally:
        if client is not None:
            client.close()
    return summarise_database_facts(facts)


def summarise_database_facts(facts):
    """Lift the few fields worth having at the top level of the record.

    The raw command output stays under ``raw``; the summary is what becomes
    VictoriaMetrics labels and Postgres columns downstream, and what a human reads
    first in the task log.

    :param facts: The collected command output.
    :return: The facts with a flat summary merged in.
    """
    build_info = facts.get("build_info") or {}
    hello = facts.get("hello") or {}
    repl = facts.get("repl_set_status") or {}
    summary = {
        "db_version": build_info.get("version"),
        "git_version": build_info.get("gitVersion"),
        "storage_engine": (facts.get("cmd_line_opts") or {})
        .get("parsed", {})
        .get("storage", {})
        .get("engine"),
        "is_writable_primary": hello.get("isWritablePrimary"),
        "is_arbiter": hello.get("arbiterOnly"),
        "msg": hello.get("msg"),
        "set_name": hello.get("setName") or repl.get("set"),
        "state": repl.get("myState"),
    }
    if "error" in facts:
        summary["error"] = facts["error"]
    if "command_errors" in facts:
        summary["command_errors"] = facts["command_errors"]
    summary["raw"] = {
        key: value
        for key, value in facts.items()
        if key not in ("error", "command_errors")
    }
    return summary


def probe(target, config, host_facts):
    """Build the complete record for one target.

    :param target: The target mapping carrying ``service``, ``host``, ``port``.
    :param config: The task config.
    :param host_facts: The already-collected host-level facts, shared across targets
        because every target on this dispatch runs on the same executor host.
    :return: The record to print as one NDJSON line.
    """
    record = {
        "service": target.get("service"),
        "host": target.get("host"),
        "port": target.get("port"),
        "collected_at": int(time.time()),
        "status": STATUS_OK,
    }
    record.update(host_facts)

    if not config.get("probe_database", True):
        record["database"] = None
        return record

    try:
        record["database"] = collect_database_facts(
            target,
            read_userinfo(credentials_path(config)),
            config.get("auth_source") or DEFAULT_AUTH_SOURCE,
            config.get("connect_timeout_ms") or DEFAULT_CONNECT_TIMEOUT_MS,
        )
        if record["database"].get("error"):
            record["status"] = STATUS_FAILED
            record["error"] = record["database"]["error"]
    except Exception as err:  # noqa: BLE001 - one target must not abort the rest
        record["status"] = STATUS_FAILED
        record["error"] = f"{type(err).__name__}: {err}"
        record["database"] = None
    return record


def credentials_path(config):
    """Return the credentials file path, defaulting under ``$HOME``.

    :param config: The task config.
    :return: The path to read credentials from, or ``None``.
    """
    configured = config.get("credentials_path")
    if configured:
        return configured
    home = os.path.expanduser("~")
    return os.path.join(home, DEFAULT_CREDENTIALS_BASENAME) if home else None


def main():
    """Collect every configured target and print one JSON object per line."""
    config = load_config()
    targets = config.get("targets") or []
    if not targets:
        print("config names no targets", file=sys.stderr)
        sys.exit(1)

    # Host-level facts are identical for every target on this dispatch, so collect
    # them once rather than per target.
    process_facts = collect_process_facts()
    host_facts = {
        "system": collect_os_facts(),
        "process": process_facts,
        # Ask the program this host actually runs, so a router reports the mongos
        # version rather than whatever mongod binary happens to be installed.
        "binary_version": collect_binary_version(process_facts.get("program")),
    }

    for target in targets:
        record = probe(target, config, host_facts)
        print(json.dumps(record, default=str), flush=True)


if __name__ == "__main__":
    main()
