"""task related functions"""


def build_alter_task_data(config):
    """
    returns a Job dict
    """

    payload = {
        "name": config["task_name"][0],
        "app": "alters",
        "commands": [
            {
                "args": [
                    f"--alter={config['alter'][0]}",
                    f"D={config['schema_name'][0]},t={config['table_name'][0]}",
                    "--execute",
                ],
                "command": "pt-online-schema-change",
                "meta": {"schema_name": config["schema_name"][0], "table_name": config["table_name"][0]},
            }
        ],
        "persist": True,
        "schedule": {"save_only": True},
        "target": config["hostname"][0],
    }
    return payload
