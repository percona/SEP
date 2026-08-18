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
import urllib.error
import urllib.request
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


def parse_config_path(argv):
    """Read the ``--config`` path out of a server's command line.

    :param argv: The full command line.
    :return: The configuration file path, or ``None``.
    """
    tokens = argv.split()
    for index, token in enumerate(tokens):
        if token in ("-f", "--config") and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith("--config="):
            return token.split("=", 1)[1]
    return None


def parse_port(argv, config_path):
    """Determine the port a server process listens on.

    The command line wins when it carries one. Otherwise the configuration file is
    read, because that is where the port usually lives -- every node in the sandbox
    is started as ``mongod --config <file>`` with the port set inside it, so an
    argv-only reading would find nothing on any of them.

    :param argv: The full command line.
    :param config_path: The configuration file the process was started with.
    :return: The port as an int, or ``None`` when neither source names one.
    """
    tokens = argv.split()
    for index, token in enumerate(tokens):
        if token == "--port" and index + 1 < len(tokens):
            if tokens[index + 1].isdigit():
                return int(tokens[index + 1])
        if token.startswith("--port="):
            value = token.split("=", 1)[1]
            if value.isdigit():
                return int(value)

    if not config_path:
        return None
    try:
        with open(config_path) as handle:
            for raw_line in handle:
                line = raw_line.strip()
                # Matches the YAML `port: 27018` and the legacy `port=27018` alike,
                # without taking a YAML parser as a dependency on the host.
                if not line.startswith("port"):
                    continue
                remainder = line[len("port") :].lstrip()
                if remainder.startswith((":", "=")):
                    value = remainder[1:].strip().split("#")[0].strip()
                    if value.isdigit():
                        return int(value)
    except OSError:
        return None
    return None


def collect_server_processes():
    """Return every mongod and mongos running on this host.

    :func:`collect_process_facts` deliberately reports only the first, because a
    probe of one service wants one answer. This is the other question -- what is
    *actually running here* -- and it has to see all of them, because the ones PMM
    has no service for are precisely the ones nothing else can tell you about.

    :return: One mapping per server process, each with its program, pid, port,
        configuration path and command line.
    """
    processes = []
    for program in SERVER_PROGRAMS:
        output = run_command(["ps", "-o", "pid=,args=", "-C", program])
        if not output:
            continue
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            pid, argv = parts
            config_path = parse_config_path(argv)
            processes.append(
                {
                    "program": program,
                    "pid": int(pid) if pid.isdigit() else None,
                    "port": parse_port(argv, config_path),
                    "config_path": config_path,
                    "argv": argv,
                }
            )
    return processes


def find_unregistered(processes, targets):
    """Return the server processes no target accounts for.

    A "target" is a service PMM has registered and asked us to probe, identified by
    its port. Anything else listening is a database PMM does not know about --
    normal rather than exotic, because an arbiter holds no data and therefore no user
    documents, so SCRAM cannot authenticate and ``pmm-admin add mongodb`` fails for
    it. Any estate with arbiters and authentication enabled has them.

    A process whose port could not be determined is reported as unregistered rather
    than dropped: it cannot be matched to a target, and silently discarding a running
    database would be exactly the dishonesty this list exists to prevent.

    :param processes: Every server process found on the host.
    :param targets: The configured targets, each carrying a ``port``.
    :return: The processes that matched no target.
    """
    registered_ports = {
        target.get("port") for target in targets if target.get("port") is not None
    }
    return [
        process
        for process in processes
        if process.get("port") is None or process["port"] not in registered_ports
    ]


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


#: The file every Percona repository client needs before it can install anything.
#: Small (about 3 KB), stable, and *load-bearing* -- an unreachable packaging key is a
#: real install blocker rather than a synthetic reachability check, which is what makes
#: it worth fetching rather than pinging the host.
DEFAULT_REPO_URL = "https://repo.percona.com/percona/yum/PERCONA-PACKAGING-KEY"

#: What the packaging key's body starts with. Checked so that a proxy or captive
#: portal answering 200 with its own page is reported as unreachable rather than as a
#: healthy repository -- which is the failure a status-code-only check gets wrong, and
#: the one most likely in the networks this exists to describe.
PACKAGING_KEY_MARKER = b"-----BEGIN PGP PUBLIC KEY BLOCK-----"

#: Short on purpose. This runs once per dispatch on the request path of a sweep, and
#: "the repository is slow" is itself the finding -- a package manager with a 30-second
#: stall is not usable in practice, so waiting 30 seconds to discover that adds nothing.
DEFAULT_REPO_TIMEOUT = 8


def collect_repo_facts(config):
    """Return whether this host can actually reach Percona's repository.

    An HTTPS GET rather than a ping or a TCP connect, because the failures worth
    catching all live above that layer: DNS that resolves nowhere useful, a TLS
    interception appliance with a certificate the host does not trust, a proxy that
    allows CONNECT but blocks this origin, a transparent cache serving 403. Every one
    of those passes a ping and fails ``yum install``.

    The proxy in effect is reported alongside the result, because without it the
    result cannot be explained: "connection refused" from a host with no proxy and
    from a host behind a broken one are the same string and completely different
    problems. Only the variable *name* and its value are read from the environment --
    a proxy URL can carry credentials, so the value is reported as configured and
    nothing tries to be clever about redacting it.

    Never raises: a repository check failing must not cost the caller the OS, process
    and version facts collected beside it.

    :param config: The task config, which may carry ``repo_url`` and
        ``repo_timeout``.
    :return: A mapping describing the attempt.
    """
    url = config.get("repo_url") or DEFAULT_REPO_URL
    timeout = config.get("repo_timeout") or DEFAULT_REPO_TIMEOUT
    proxy = (
        os.environ.get("https_proxy")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("http_proxy")
        or os.environ.get("HTTP_PROXY")
    )
    facts = {
        "url": url,
        "reachable": False,
        "status_code": None,
        "latency_ms": None,
        "proxy": proxy,
        "error": None,
    }

    started = time.time()
    try:
        # urllib honours the proxy environment variables by default, which is the
        # behaviour wanted here: the check should go the same way a package manager
        # would rather than a way only this payload knows about.
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            # Read the body rather than trusting the status line. A proxy or captive
            # portal answering 200 with its own HTML is a failure that a status-only
            # check reports as success, and reading is what a package manager does.
            body = response.read(len(PACKAGING_KEY_MARKER) + 64)
            facts["status_code"] = response.status
            facts["reachable"] = PACKAGING_KEY_MARKER in body
            if not facts["reachable"]:
                facts["error"] = (
                    "the response did not look like the packaging key -- something "
                    "answered, but not the repository"
                )
    except urllib.error.HTTPError as err:
        facts["status_code"] = err.code
        facts["error"] = f"HTTP {err.code}: {err.reason}"
    except Exception as err:  # noqa: BLE001 - a repo check must not fail the sweep
        facts["error"] = f"{type(err).__name__}: {err}"
    facts["latency_ms"] = int((time.time() - started) * 1000)
    return facts


def main():
    """Print one JSON object for the host, then one per configured target.

    The host line comes first and is emitted whether or not there are targets. A
    dispatch with no targets is not a misconfiguration: a machine carrying a PMM
    client and no database is exactly what POM wants to describe, and it is the state
    a host is in before anything is installed on it. Refusing to run there -- which
    this did, exiting 1 on an empty target list -- left the only hosts worth an
    install decision as the only hosts POM could say nothing about.

    The host line also stops host attributes being read off whichever service record
    happened to answer. They belong to the host, they are collected once per
    dispatch, and now they are reported once too.
    """
    config = load_config()
    targets = config.get("targets") or []

    # Collected once: identical for every target on this dispatch, because they all
    # run on the same executor host.
    process_facts = collect_process_facts()
    host_facts = {
        "system": collect_os_facts(),
        "process": process_facts,
        # Ask the program this host actually runs, so a router reports the mongos
        # version rather than whatever mongod binary happens to be installed.
        "binary_version": collect_binary_version(process_facts.get("program")),
        # Once per dispatch, like the OS facts: it is a property of the host, and
        # asking once per service would multiply the wait by the services on it.
        "repo": collect_repo_facts(config),
    }

    # ``service: null`` is what marks this the host's own record. The consumer keys
    # service records by name, so a record with no name cannot be mistaken for one.
    host_record = {
        "service": None,
        "collected_at": int(time.time()),
        "status": STATUS_OK,
    }
    host_record.update(host_facts)
    # What is running here that PMM did not ask about. Reported on the host rather
    # than as a service of its own: there is no service id to key one on, and
    # inventing an identity for a database PMM does not monitor would commit to a
    # shape before anyone needs it. Dropping them instead would let the estate view
    # claim a host is empty while a mongod is running on it.
    host_record["unregistered_mongods"] = find_unregistered(
        collect_server_processes(), targets
    )
    print(json.dumps(host_record, default=str), flush=True)

    for target in targets:
        record = probe(target, config, host_facts)
        print(json.dumps(record, default=str), flush=True)


if __name__ == "__main__":
    main()
