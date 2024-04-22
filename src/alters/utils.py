"""Utility functions"""

from sep.tasks.nomad.models import Payload


def build_task_payload(config) -> Payload:
    """Create a payload for the backend

    :param config:
    :return:
    """
    return Payload(
        name=config["task_name"][0],
        app="alters",
        args=[
            f"--alter={config['alter'][0]}",
            f"D={config['schema_name'][0]},t={config['table_name'][0]}",
            "--execute",
        ],
        command="pt-online-schema-change",
        meta={"schema_name": config["schema_name"][0], "table_name": config["table_name"][0]},
        target=config["hostname"][0],
    )
