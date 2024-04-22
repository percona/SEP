"""task related functions"""

from typing import Union

import yaml

from sep.tasks.nomad.models import Payload

PURGE_TABLES_CONFIG_WHERE = {
    "ALL": {"SOURCE_HOST": None, "SOURCE_PORT": 0},
    "PURGE_LIST": [{"ALIAS": None, "SOURCE_DB": None, "SOURCE_TABLE": None, "DEST_TABLE": None, "WHERE": None}],
}


def build_task_payload(config) -> Payload:
    """Create a payload for the backend

    :param config:
    :return:
    """
    match config["archive_type"]:
        case ["where"]:
            purge_config = PURGE_TABLES_CONFIG_WHERE.copy()
        case _:
            raise NotImplementedError("Currently only 'where' is supported")

    purge_config_all = purge_config["ALL"]
    purge_config_list = purge_config["PURGE_LIST"][0]
    purge_config_all.update(SOURCE_HOST=config["hostname"][0], SOURCE_PORT=3306)
    purge_config_list.update(
        ALIAS=config["task_name"][0],
        SOURCE_DB=config["sourcedb"][0],
        SOURCE_TABLE=config["sourcetbl"][0],
        DEST_TABLE=config["dest_name"][0],
        WHERE=config["where"][0],
    )
    purge_config.update(ALL=purge_config_all, PURGE_LIST=[purge_config_list])

    return Payload(
        name=config["task_name"][0],
        app="archiver",
        args=[
            f"--alias={config['task_name'][0]}",
            "--config=${NOMAD_TASK_DIR}/purge_tables.yaml",
        ],
        command="/home/percona/bin/purge-tables.py",
        config=[
            {
                "content": yaml.dump(purge_config),
                "path": "purge_tables.yaml",
            }
        ],
        target=config["hostname"][0],
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
            case "hostname":
                data[item] = config["ALL"]["SOURCE_HOST"]
            case "name":
                data[item] = config["PURGE_LIST"][0]["ALIAS"]
            case "table":
                data[item] = f'{config["PURGE_LIST"][0]["SOURCE_DB"]}.{config["PURGE_LIST"][0]["SOURCE_TABLE"]}'
            case _:
                data[item] = config.get(item)
    return data
