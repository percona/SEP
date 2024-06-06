"""task related functions"""

from typing import Union

import yaml

from sep.tasks.api.models import GeneratedTask


SERVER_LIST = {"ALIAS": "Default_alias", "BACKUP_TYPE": "X", "HOST": "locahost", "UPLOAD": None}

MYSQL_BACKUPS_CONFIG = {
    "ALL_SERVERS": {"LOGGING_DIR": "/var/log/percona/backups",
                    "BACKUP_DIR": "/percona-backups",
                    "PORT": 3306,
                    "HARDLINK": True,
                    "COMPRESS": True,
                    "CHECK_DISK_SPACE": False,
                    "POST_RUN_ENCRYPT": False,
                    "ONLY_IF_RUNNING_SLAVE": False,
                    "ONLY_IF_READ_ONLY": False,
                    "DEBUG": "no",
                    "DEFAULTS_FILE": "/home/percona/.my.cnf",
                    "MYCNF_PATH": "/etc/mysql/my.cnf",
                    "SKIP_PENDING_SHUTDOWN": False,
                    "XTRABACKUP_COPIES": 2,
                    "XTRABACKUP_KILL_QUERIES": True,
                    "XTRABACKUP_KILL_QUERIES_TIMEOUT": "10",
                    "XTRABACKUP_KILL_QUERY_TYPE": "select",
                    "XTRABACKUP_RLIMIT": "[65536, 65536]",
                    "XTRABACKUP_VERIFY": True,
                    "XTRABACKUP_PREPARE": False,
                    "XTRABACKUP_PREPARE_MEMORY": "2G",
                    "XTRABACKUP_DESYNC_PXC": False,
                    "XTRABACKUP_RSYNC": True,
                    "XTRABACKUP_SLAVE_INFO": True,
                    "XTRABACKUP_DEFAULTS_FILE": False,
                    "XTRABACKUP_EXTRA_ARGS": None,
                    "XTRABACKUP_INCREMENTAL_METHOD": "less_space",
                    "XTRABACKUP_INCREMENTAL_CYCLE": "weekly",
                    "XTRABACKUP_AES256_KEYFILE": None,
                    "XTRABACKUP_STOP_SLAVE": False,
                    "XTRABACKUP_LOCK_DDL": False,
                    "XTRABACKUP_LOCK_DDL_TIMEOUT": "60",
                    "XTRABACKUP_BIN_CMD": "xtrabackup"
                    },
    "CRON_ENTRIES": [],
    "SERVER_LIST": [],
}

'''
job "docs" {
  periodic {
    cron             = "*/15 * * * * *"
    prohibit_overlap = true
  }
}

JSON

  "Periodic": {
    "Spec": "*/15 - *",
    "TimeZone": "Europe/Berlin",
    "SpecType": "cron",
    "Enabled": true,
    "ProhibitOverlap": true
  }
'''

def build_task_payload(config) -> GeneratedTask:
    """Create a payload for the backend

    :param config:
    :return:
    """
    backup_config = MYSQL_BACKUPS_CONFIG.copy()
    backup_config_list = SERVER_LIST.copy()

    # Set general configs
    backup_config_all = backup_config["ALL_SERVERS"]
    backup_config_all.update(
        LOGGING_DIR=config["logging_dir"][0],
        BACKUP_DIR=config["backup_dir"][0],
        PORT=config['port'][0],
        HARDLINK=config.get('hardlink', [False])[0],
        COMPRESS=config.get('compress', [False])[0],
        CHECK_DISK_SPACE=config.get('check_disk_space', [False])[0],
        POST_RUN_ENCRYPT=config.get('post_run_encrypt', [False])[0],
        ONLY_IF_RUNNING_SLAVE=config.get('only_if_running_slave', [False])[0],
        ONLY_IF_READ_ONLY=config.get('only_if_read_only', [False])[0],
        DEBUG=config.get('debug', [False])[0],
        DEFAULTS_FILE=config['defaults_file'][0],
        MYCNF_PATH=config['mycnf_path'][0],
        SKIP_PENDING_SHUTDOWN=config.get('skip_pending_shutdown', [False])[0],
        XTRABACKUP_COPIES=int(config['XTRABACKUP_COPIES'][0]),
        XTRABACKUP_KILL_QUERIES=config.get('XTRABACKUP_KILL_QUERIES', [False])[0],
        XTRABACKUP_KILL_QUERIES_TIMEOUT=config['XTRABACKUP_KILL_QUERIES_TIMEOUT'][0],
        XTRABACKUP_KILL_QUERY_TYPE=config['XTRABACKUP_KILL_QUERY_TYPE'][0],
        XTRABACKUP_RLIMIT=config['XTRABACKUP_RLIMIT'][0],
        XTRABACKUP_VERIFY=config.get('XTRABACKUP_VERIFY', [False])[0],
        XTRABACKUP_PREPARE=config.get('XTRABACKUP_PREPARE', [False])[0],
        XTRABACKUP_PREPARE_MEMORY=config['XTRABACKUP_PREPARE_MEMORY'][0],
        XTRABACKUP_DESYNC_PXC=config.get('XTRABACKUP_DESYNC_PXC', [False])[0],
        XTRABACKUP_RSYNC=config.get('XTRABACKUP_RSYNC', [False])[0],
        XTRABACKUP_SLAVE_INFO=config.get('XTRABACKUP_SLAVE_INFO', [False])[0],
        XTRABACKUP_DEFAULTS_FILE=config.get('XTRABACKUP_DEFAULTS_FILE', [False])[0],
        XTRABACKUP_EXTRA_ARGS=config.get('XTRABACKUP_EXTRA_ARGS', [False])[0],
        XTRABACKUP_INCREMENTAL_CYCLE=config['XTRABACKUP_INCREMENTAL_CYCLE'][0],
        XTRABACKUP_AES256_KEYFILE=config.get('XTRABACKUP_AES256_KEYFILE', [False])[0],
        XTRABACKUP_STOP_SLAVE=config.get('XTRABACKUP_STOP_SLAVE', [False])[0],
        XTRABACKUP_LOCK_DDL=config.get('XTRABACKUP_LOCK_DDL', [False])[0],
        XTRABACKUP_LOCK_DDL_TIMEOUT=config['XTRABACKUP_LOCK_DDL_TIMEOUT'][0],
        XTRABACKUP_BIN_CMD=config['XTRABACKUP_BIN_CMD'][0]
    )
    backup_config.update(ALL_SERVERS=backup_config_all)

    # In the future this will be a loop
    backup_config_list = SERVER_LIST.copy()
    backup_config_list.update(
        ALIAS=config["alias"][0],
        BACKUP_TYPE=config["backup_type"][0],
        HOST=config["host"][0],
        UPLOAD=config["upload"][0]
    )
    backup_config['SERVER_LIST'].append(backup_config_list)

    # Scheduler not impletemented yet
    #schedule = {
    #                "Spec": "*/15 * * * * *",
    #                "SpecType": "cron",
    #                "Enabled": True,
    #                "ProhibitOverlap": True
    #            }

    return GeneratedTask(
        app="mysql_backups",
        commands=[
            {
                "args": [
                    "/usr/local/percona/msp/backup/bin/backup_xtrabackup.py",
                    f"--server={config['alias'][0]}",
                    "--config=${NOMAD_TASK_DIR}/backup_config.yaml",
                ],
                "command": "sudo",
                "config": [
                    {
                        "content": yaml.dump(backup_config),
                        "path": "local/backup_config.yaml",
                    }
                ],
            }
        ],
        name=config['task_name'][0],
        target=config["hostname"][0],
        #schedule=schedule
    )


def extract_task_values(config: Union[dict, str], items: list) -> dict:
    """Extract data from the task's config file

    :param config:
    :param items:
    :return:
    """
    if not isinstance(config, dict):
        try:
            config = yaml.safe_load(config)
        except yaml.YAMLError:
            return {}
    data = {}
    for item in items:
        match item:
            case "all":
                data[item] = config
            case "hostname":
                data[item] = config["SERVER_LIST"][0]["HOST"]
            case "name":
                data[item] = config["SERVER_LIST"][0]["ALIAS"]
            case "type":
                data[item] = config["SERVER_LIST"][0]["BACKUP_TYPE"]
            case _:
                data[item] = config.get(item)
    return data
