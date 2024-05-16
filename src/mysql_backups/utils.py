"""task related functions"""

from typing import Union

import yaml

from sep.tasks.api.models import GeneratedTask

MYSQL_BACKUPS_CONFIG_X = {
    "ALL_SERVERS": {"LOGGING_DIR": "/var/log/percona/backups",
                    "BACKUP_DIR": "/percona-backups"},
    "CRON_ENTRIES": [],
    "SERVER_LIST": [{"ALIAS": "Default_alias", "BACKUP_TYPE": "X", "HOST": "locahost", "UPLOAD": None}],
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
    print(config)
    backup_config = MYSQL_BACKUPS_CONFIG_X.copy()
    '''
    match config["backup_type"]:
        case ["X"]:
            backup_config = MYSQL_BACKUPS_CONFIG_X.copy()
        case _:
            raise NotImplementedError("Currently only 'xtrabackup' is supported")
    '''
    backup_config_all = backup_config["ALL_SERVERS"]
    backup_config_list = backup_config["SERVER_LIST"][0]
    backup_config_all.update(LOGGING_DIR=config["logging_dir"][0],
                             BACKUP_DIR=config["backup_dir"][0])
    backup_config_list.update(
        ALIAS=config["alias"][0],
        BACKUP_TYPE=config["backup_type"][0],
        HOST=config["host"][0],
        UPLOAD=config["upload"][0]
    )
    backup_config.update(ALL_SERVERS=backup_config_all,
                         SERVER_LIST=[backup_config_list])

    return GeneratedTask(
        app="mysql_backups",
        commands=[
            {
                "args": [
                    f"--alias={config['alias'][0]}",
                    "--config=${NOMAD_TASK_DIR}/backup_config.yaml",
                ],
                "command": "/usr/local/percona/msp/backup/bin/backup_xtrabackup.py",
                "config": [
                    {
                        "content": yaml.dump(backup_config),
                        "path": "backup_config.yaml",
                    }
                ],
            }
        ],
        name=f"mysql_backups_{config['hostname'][0]}",
        target=config["hostname"][0],
        schedule={
                    "Spec": "*/15 * * * * *",
                    "SpecType": "cron",
                    "Enabled": True,
                    "ProhibitOverlap": True
                }
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
