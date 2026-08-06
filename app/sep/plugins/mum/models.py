"""Define models for the MUM plugin."""

from typing import Literal

from pydantic import BaseModel

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, Field, RequiredStr


class MongoDBUsername(BaseCaseInsensitiveModel):
    """Represent the overall getuser_request configuration.
    :param get_user_json_payload: The PBM yaml payload to parse from CLI.
    :type get_user_json_payload: RequiredStr | EmptyStrToNone
    """

    get_user_json_payload: RequiredStr | EmptyStrToNone = Field(
        None, serialization_alias="get_user_json_payload"
    )


class MongoDBUser(BaseCaseInsensitiveModel):
    """Pydantic model representing all attributes of a MongoDB user.
    """

    id: str
    username: MongoDBUsername
    db: str
    roles: list[dict] = Field(
        ...,
        description="A list of documents, where each document specifies a role and the database to which the role applies."
    )
    customData: EmptyStrToNone
    mechanisms: EmptyStrToNone
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "id": "651f67b82f0a1c1a9b2b3a4d",
                "user": "myUser",
                "db": "admin",
                "roles": [
                    {
                        "role": "readWrite",
                        "db": "myDatabase"
                    },
                    {
                        "role": "dbAdmin",
                        "db": "myDatabase"
                    }
                ],
                "creationTime": "2023-10-06T13:00:00Z",
                "credentials": {
                    "SCRAM-SHA-256": {
                        "iterationCount": 10000,
                        "salt": "aGVsbG8gd29ybGQ=",
                        "storedKey": "c3RvcmVkS2V5",
                        "serverKey": "c2VydmVyS2V5"
                    }
                },
                "customData": {
                    "department": "IT",
                    "employeeId": "12345"
                },
                "mechanisms": [
                    "SCRAM-SHA-256"
                ],
                "pwd": None
            }
        }


class GetUserRequest(BaseCaseInsensitiveModel):
    """Represent a Backup creation form with proper case-insensitive fields.
    :param task_name: The PBM yaml payload to parse from CLI.
    :type task_name: RequiredStr
    :param hostname: The PBM yaml payload to parse from CLI.
    :type hostname: RequiredStr
    :param service_id: Service for executing PBM.
    :type service_id: int
    :param backup_type: Type of backup activity on PBM.
    :type backup_type: BackupType
    :param alert_on_fail: If True, send an alert if the task fails. Defaults to False.
    :type alert_on_fail: bool
    """

    task_name: RequiredStr
    hostname: RequiredStr
    service_id: int
    username: MongoDBUser


class MUMTaskCreateRequest(BaseModel):
    """Request body for creating a MUM task via JSON.
    :param name: The unique name of the task to create.
    :param payload: The payload for the task transformation.
    :param fmt: The format of the payload (hcl, json, yaml).
    :param alert_on_fail: Whether to alert when the task fails.
    """

    name: RequiredStr
    payload: RequiredStr
    fmt: Literal["hcl", "json", "yaml"]
    alert_on_fail: bool = False
