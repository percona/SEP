#!/usr/bin/env python
"""
Script to purge tables. Can alert using Nagios when appropriate.

TODO:
 - check slave lag --check-slave-lag --max-lag
 - safe checks (FKs, purging more than 75% of data)
 - compress file

Copyright 2012 by Percona LLC or its affiliates, all rights reserved.
"""

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser
import logging
import os
import socket
import subprocess
import sys
import time
import yaml

try:
    import pymysql as mysql
    from pymysql.err import OperationalError, ProgrammingError

    mysql.install_as_MySQLdb()
except ImportError:
    import MySQLdb as mysql  # noqa
    from _mysql_exceptions import OperationalError, ProgrammingError  # noqa

LOGGING_DIR = "/var/log/percona"
LOGGING_FILE = "purge_tables.log"
LOGGING_FORMAT = "%(asctime)s::PID <%(process)d>::%(levelname)s::%(message)s"
LOGGING_LVL = logging.INFO

try:
    if not os.path.isdir(LOGGING_DIR):
        os.makedirs(LOGGING_DIR)
except os.error:
    logging.exception("Unable to create %s", LOGGING_DIR)
    sys.exit(2)
else:
    logging.basicConfig(filename=os.path.join(LOGGING_DIR, LOGGING_FILE), level=LOGGING_LVL, format=LOGGING_FORMAT)

PT_ARCHIVER_BIN = "/usr/bin/pt-archiver"
CFG_FILE = "/etc/rdba/purge_tables.yml"


def main():  # noqa pylint: disable=too-many-locals, too-many-statements, too-many-branches
    """Main Function"""

    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument("-c", "--conf", help="path to options file")
    parser.add_argument("-l", "--lockfile", help="Path to lock file")
    parser.add_argument("-a", "--alias", help="Purge process to run")
    parser.add_argument("-d", "--dry-run", action="store_true", default=False, help="Dry run instead of execute")
    parser.add_argument("-s", "--stop-on-error", action="store_true", default=False, help="Stop when one fails.")
    options = parser.parse_args()

    # if options.lockfile is None:
    #     lockfile_name = '/tmp/.purge_tables.lock'
    # else:
    #     lockfile_name = options.lockfile

    try:  # pylint: disable=too-many-nested-blocks
        # lockfile = lockfile_lib.LockFile(lockfile_name, timeout=600)
        # lockfile.get_lock_or_exit()

        if options.conf is None:
            cfg_path = CFG_FILE
        else:
            cfg_path = options.conf

        try:
            with open(cfg_path) as cfg_file:
                cfg_file_contents = cfg_file.read()
                data = yaml.safe_load(cfg_file_contents)
        except (AttributeError, IOError, TypeError, yaml.parser.ParserError):
            logging.exception("Could not read config file %r", cfg_path)
            return

        purge_data_list = []
        default_purge = {}

        default_purge.update(data["ALL"])

        for purge in data["PURGE_LIST"]:
            purge_data = default_purge.copy()
            purge_data.update(purge)
            purge_data_list.append(purge_data)

        purges = [b for b in purge_data_list]
        if options.alias is not None:
            purges = [b for b in purges if options.alias == (b["ALIAS"])]

        for purge in purges:
            conf = {
                "nsca_report": {
                    "nagios_server": purge.get("NAGIOS_SERVER"),
                    "nsca_password": purge.get("NSCA_PASSWORD"),
                    "nsca_hostname": str(purge.get("NSCA_HOSTNAME", socket.gethostname().split(".")[0])),
                    "check_name": str(purge.get("NSCA_CHECK_NAME", "Purge Tables")),
                },
                "prg_alias": purge.get("ALIAS"),
                "src_host": purge.get("SOURCE_HOST", "localhost"),
                "src_port": purge.get("SOURCE_PORT", 3306),
                "src_db": purge.get("SOURCE_DB"),
                "src_tbl": purge.get("SOURCE_TABLE"),
                "src_query": purge.get("SOURCE_QUERY"),
                "dst_host": purge.get("DEST_HOST"),
                "dst_port": purge.get("DEST_PORT"),
                "dst_db": purge.get("DEST_DB"),
                "dst_tbl": purge.get("DEST_TABLE"),
                "dst_file": purge.get("DEST_FILE"),
                "prg_where": purge.get("WHERE"),
                "prg_limit": purge.get("LIMIT", 1000),
                "prg_sleep": purge.get("SLEEP", 1),
                "prg_purge": purge.get("DELETE_DATA", 0),
                "prg_extra_args": purge.get("EXTRA_ARGS"),
                "prg_disable_binlog": purge.get("DISABLE_BINLOG", 0),
                "prg_use_index": purge.get("USE_INDEX", None),
                "prg_send_notifications": purge.get("SLACK_NOTIFICATIONS", 0),
                "swp_drp": purge.get("SWAP_DROP", 0),
                "swp_table_suffix": purge.get("SWP_TABLE_SUFFIX", time.strftime("%Y%m%d")),
            }

            for key in ("host", "port", "db", "tbl"):
                if not conf["dst_" + key]:
                    conf["dst_" + key] = conf["src_" + key]

            start_time = time.time()
            logging.info(">>>>>>>>>>>>>>>>>> Purge started.")

            if conf["swp_drp"] not in (0, 1, 2):
                logging.error("<%s> Please ensure SWAP_DROP is set between 0 and 2.", conf["prg_alias"])
                return

            if not conf["prg_where"] and conf["swp_drp"] == 0:
                logging.error("<%s> Please add a WHERE clause.", conf["prg_alias"])
                return

            prg_log_file = os.path.join(
                LOGGING_DIR, "purge_tables-%s-%s.log" % (conf["prg_alias"], time.strftime("%Y%m%d"))
            )
            prg_log_stream = open(prg_log_file, "a")

            tables_to_purge = []
            if conf["src_query"]:
                tables_to_purge = get_tables_from_query(conf["src_host"], conf["src_port"], conf["src_query"])
            else:
                tables_to_purge.append({"database": conf["src_db"], "table": conf["src_tbl"]})

            error_on_alias = []
            for table in tables_to_purge:
                src_db = table["database"]
                src_tbl = table["table"]

                if conf["swp_drp"] == 0:
                    ret = pt_archive_runner(src_db, src_tbl, conf, options, prg_log_stream)
                elif conf["swp_drp"] == 1:
                    ret = swap_drop_runner(src_db, src_tbl, conf, options, prg_log_stream)
                elif conf["swp_drp"] == 2:
                    # SWAP-ARCHIVE-DROP
                    # SWAP
                    src_tbl_swapped = src_tbl + "_" + conf["swp_table_suffix"]
                    ret = swap_create_table(src_db, src_tbl, src_tbl_swapped, conf, options, prg_log_stream)
                    if ret == 0:
                        # ARCHIVE
                        # we need to re-set dst_table
                        conf["dst_tbl"] = src_tbl_swapped
                        ret = pt_archive_runner(src_db, src_tbl_swapped, conf, options, prg_log_stream)
                        if ret == 0:
                            # DROP
                            ret = drop_table(src_db, src_tbl_swapped, conf, options, prg_log_stream)

                if ret != 0:
                    msg = "Check {}".format(prg_log_file)
                    logging.error("<%s> ERROR: Purge Failed. %s", conf["prg_alias"], msg)
                    #                    nsca_notify(2, conf['nsca_report'], msg, conf['prg_alias'])
                    error_on_alias.append(conf["prg_alias"])
                    #                    notify_slack(msg, level=logging.ERROR, enabled=conf['prg_send_notifications'],
                    #                                 title='Purge Failed for {}'.format(conf['prg_alias']))
                    logging.info(">>>>>>>>>>>>>>>>>> Purge failed.")
                    if options.stop_on_error:
                        sys.exit(1)
                    else:
                        continue

            time_spent = format_seconds_to_hhmmss(time.time() - start_time)
            if conf["prg_alias"] not in error_on_alias:
                output = "OK <%s> Purge complete. Duration: %s." % (conf["prg_alias"], time_spent)
                logging.info("<%s> %s", conf["prg_alias"], output)
            #                notify_slack('Duration: {}'.format(time_spent), enabled=conf['prg_send_notifications'],
            #                            title='Purge complete for {}'.format(conf['prg_alias']))

            # Compress if --file
            # if dst_file:

            # Sending OK notification to Nagios
            #                if not options.dry_run:
            #                    nsca_notify(0, conf['nsca_report'], output, conf['prg_alias'])

            logging.info(">>>>>>>>>>>>>>>>>> Purge finished. Total duration: %s.", time_spent)
    except Exception:  # pylint: disable=broad-except
        logging.error("Unhandled exception", exc_info=True)


#    finally:
#        lockfile.free_lock()


def drop_table(src_db, src_tbl, conf, options, prg_log_stream):
    """Drop table"""
    sql_cmd = "DROP TABLE {0}.{1};".format(src_db, src_tbl)
    drp_cmd = ["mysql", src_db, "-h%s" % (conf["src_host"]), "-P%s" % (conf["src_port"]), "-e%s" % (sql_cmd)]
    if options.dry_run:
        print(" ".join(drp_cmd))
        print("NOTE: dry-run just shows the SQL for drop_table")
        ret = 0
    else:
        purge_proc = subprocess.Popen(drp_cmd, stdout=prg_log_stream, stderr=prg_log_stream)  # noqa
        purge_proc.communicate()
        ret = purge_proc.returncode
    return ret


def swap_create_table(src_db, src_tbl, src_tbl_swapped, conf, options, prg_log_stream):
    """Swap table"""

    sql_cmd = (
        "CREATE TABLE {0}.{1}_tmp LIKE {0}.{1};" "RENAME TABLE {0}.{1} TO {0}.{2}, {0}.{1}_tmp TO {0}.{1};".format(
            src_db, src_tbl, src_tbl_swapped
        )
    )
    drp_swp_cmd = ["mysql", src_db, "-h%s" % (conf["src_host"]), "-P%s" % (conf["src_port"]), "-e%s" % (sql_cmd)]
    if options.dry_run:
        print(str(drp_swp_cmd))
        print("[NOTE: dry-run just shows the SQL for swap_create_table]")
        ret = 0
    else:
        purge_proc = subprocess.Popen(drp_swp_cmd, stdout=prg_log_stream, stderr=prg_log_stream)  # noqa
        purge_proc.communicate()
        ret = purge_proc.returncode
    if ret == 0:
        # create table on dest
        dump_cmd = [
            "mysqldump",
            "-h%s" % (conf["src_host"]),
            "-P%s" % (conf["src_port"]),
            "--skip-opt",
            "--no-data",
            "--no-create-db",
            src_db,
            src_tbl_swapped,
        ]
        create_cmd = ["mysql", "-h%s" % (conf["dst_host"]), "-P%s" % (conf["dst_port"]), conf["dst_db"]]
        if options.dry_run:
            print(" ".join(dump_cmd))
            print(" ".join(create_cmd))
        else:
            dump_proc = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE)  # noqa
            create_proc = subprocess.Popen(
                create_cmd, stdin=dump_proc.stdout, stdout=prg_log_stream, stderr=prg_log_stream  # noqa
            )
            create_proc.communicate()
            ret = create_proc.returncode
    return ret


def swap_drop_runner(src_db, src_tbl, conf, options, prg_log_stream):
    """Swap and drop table"""

    sql_cmd = "CREATE TABLE %s_new like %s;" % (src_tbl, src_tbl)
    sql_cmd = "%s RENAME TABLE %s TO %s_old, %s_new To %s;" % (sql_cmd, src_tbl, src_tbl, src_tbl, src_tbl)
    sql_cmd = "%s DROP TABLE %s_old" % (sql_cmd, src_tbl)
    drp_swp_cmd = ["mysql", src_db, "-h%s" % (conf["src_host"]), "-P%s" % (conf["src_port"]), "-e%s" % (sql_cmd)]
    if options.dry_run:
        print(str(drp_swp_cmd))
        print("[NOTE: dry-run just shows the SQL for swap-drop]")
        ret = 0
    else:
        purge_proc = subprocess.Popen(drp_swp_cmd, stdout=prg_log_stream, stderr=prg_log_stream)  # noqa
        purge_proc.communicate()
        ret = purge_proc.returncode
    return ret


def pt_archive_runner(src_db, src_tbl, conf, options, prg_log_stream):
    """Run pt-archiver"""

    if conf["prg_use_index"]:
        source_args = "--source=h=%s,P=%s,D=%s,t=%s,b=%s,i=%s" % (
            conf["src_host"],
            conf["src_port"],
            src_db,
            src_tbl,
            conf["prg_disable_binlog"],
            conf["prg_use_index"],
        )
    else:
        source_args = "--source=h=%s,P=%s,D=%s,t=%s,b=%s" % (
            conf["src_host"],
            conf["src_port"],
            src_db,
            src_tbl,
            conf["prg_disable_binlog"],
        )

    pt_archiver_cmd = [
        PT_ARCHIVER_BIN,
        source_args,
        "--where=%s" % conf["prg_where"],
        "--limit=%s" % conf["prg_limit"],
        "--progress=100000",
        "--why-quit",
        "--header",
        "--sleep=%s" % conf["prg_sleep"],
        "--statistics",
        "--skip-foreign-key-checks",
        "--commit-each",
        "--no-check-charset",
    ]

    # --bulk-insert implies --bulk-delete which implies --commit-each
    # so we need to just care about --limit (default: 1000)
    # ^^ from documentation but because of a bug we need to set --commit-each
    if conf["prg_purge"]:
        pt_archiver_cmd.extend(["--bulk-delete", "--purge"])
    elif conf["dst_file"]:
        pt_archiver_cmd.extend(["--buffer", "--bulk-delete", "--file=%s" % conf["dst_file"]])
    else:
        pt_archiver_cmd.extend(
            [
                "--bulk-insert",
                "--dest=h=%s,P=%s,D=%s,t=%s,b=%s,L=yes"
                % (conf["dst_host"], conf["dst_port"], conf["dst_db"], conf["dst_tbl"], conf["prg_disable_binlog"]),
            ]
        )

    if options.dry_run:
        pt_archiver_cmd.append("--dry-run")

    if conf["prg_extra_args"]:
        pt_archiver_cmd.extend(conf["prg_extra_args"].split(" "))

    output = "{}".format(" ".join(pt_archiver_cmd))
    logging.info("<%s> ---> Running: %s", conf["prg_alias"], output)
    #    notify_slack('`{}`'.format(output), enabled=conf['prg_send_notifications'],
    #                 title='Purge Tables: {} ---> Starting'.format(conf['prg_alias']))

    if options.dry_run:
        purge_proc = subprocess.Popen(pt_archiver_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa
    else:
        purge_proc = subprocess.Popen(pt_archiver_cmd, stdout=prg_log_stream, stderr=prg_log_stream)  # noqa
    out, err = purge_proc.communicate()
    if options.dry_run:
        print(out)
        print(err)
    ret = purge_proc.returncode
    return ret


def get_tables_from_query(host, port, sql):
    """
    Returns a list dicts of tables to be purged
    Query must return DATABASE on the first column and TABLE on the second column
    """
    tables = []
    try:
        conn = mysql.connect(read_default_group="client", host=host, port=port)
        curs = conn.cursor()
        curs.execute(sql)
        res = curs.fetchall()
    except (OperationalError, ProgrammingError) as err:
        logging.error(err)
        return tables

    try:
        for row in res:
            tables.append({"database": row[0], "table": row[1]})
    except IndexError as err:
        logging.error(err)

    return tables


def format_seconds_to_hhmmss(seconds):
    """Formats seconds in HH:MM:SS format"""
    hours = seconds // (60 * 60)
    seconds %= 60 * 60
    minutes = seconds // 60
    seconds %= 60
    return "%02i:%02i:%02i" % (hours, minutes, seconds)


if __name__ == "__main__":
    main()
