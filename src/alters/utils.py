"""Utility functions"""

from sep.tasks.api.models import GeneratedTask


def build_task_payload(config) -> GeneratedTask:
    """Create a payload for the backend

    :param config:
    :return:
    """

    if config["connect_to"][0] == 'localhost':
        dsn = f"D={config['schema_name'][0]},t={config['table_name'][0]}"
    else:
        dsn = f"h={config['hostname'][0]},D={config['schema_name'][0]},t={config['table_name'][0]}"

    if config['recursion_method'][0] == 'dsn':
        recursion_method = f"dsn={config['dsn_table'][0]}"
    else:
        recursion_method = config['recursion_method'][0]

    return GeneratedTask(
        app="alters",
        commands=[
            {
                "args": [
                    f"--alter={config['alter'][0]}",
                    dsn,
                    f"--recursion-method={recursion_method}",
                    "--execute",
                ],
                "command": "pt-online-schema-change",
                "meta": {"schema_name": config["schema_name"][0], "table_name": config["table_name"][0]},
            }
        ],
        name=config["task_name"][0],
        target=config["hostname"][0],
    )
