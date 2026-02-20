"""Define tests for the app.sep.plugins.mum.routes module."""

import json

import pytest
from fastapi import HTTPException, status


@pytest.mark.usefixtures("mock_get_username_mapping")
def test_mum_create_user_uses_nomad_variable_for_password(test_client, mock_task_api_dep):
    """Ensure create-user sends password to Nomad variable, not task meta."""
    mock_task_api_dep.get.side_effect = [
        HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    ]
    mock_task_api_dep.post.side_effect = [
        {"path": "ignored"},
        {"id": 10, "name": "mum-user-create"},
        {"id": 100, "status": "RUNNING"},
    ]

    response = test_client.post(
        "/mum/ui/create-user",
        json={
            "target": "node-a",
            "username": "alice",
            "password": "plain-password",
            "roles": ["readWrite"],
            "db": "admin",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    first_post = mock_task_api_dep.post.await_args_list[0]
    assert first_post.args[0] == "/nomad/variables/"
    assert first_post.kwargs["json"]["data"]["config"]["password"] == "plain-password"

    execute_post = mock_task_api_dep.post.await_args_list[2]
    assert execute_post.args[0] == "/execute/mum-user-create"
    execute_meta = execute_post.kwargs["json"]["meta"]
    assert execute_meta["target"] == "node-a"
    assert execute_meta["_job_id_prefix"].startswith("mum-")
    assert execute_meta["config_nomad_variable"].startswith("sep/runtime/mum/mum-")
    assert "config" not in execute_meta
    assert "plain-password" not in json.dumps(execute_meta)


@pytest.mark.usefixtures("mock_get_username_mapping")
def test_mum_create_user_deletes_variable_if_dispatch_fails(
    test_client, mock_task_api_dep
):
    """Ensure create-user cleans up Nomad variable when execution fails."""
    mock_task_api_dep.get.return_value = {"id": 10, "name": "mum-user-create"}
    mock_task_api_dep.post.side_effect = [
        {"path": "ignored"},
        HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dispatch failed"),
    ]

    response = test_client.post(
        "/mum/ui/create-user",
        json={
            "target": "node-a",
            "username": "alice",
            "password": "plain-password",
            "roles": ["readWrite"],
            "db": "admin",
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {"detail": "dispatch failed"}
    delete_call = mock_task_api_dep.delete.await_args
    assert delete_call.args[0].startswith("/nomad/variables/sep/runtime/mum/mum-")


@pytest.mark.usefixtures("mock_get_username_mapping")
def test_mum_update_user_without_password_skips_nomad_variable(
    test_client, mock_task_api_dep
):
    """Ensure update-user without password does not create Nomad variable."""
    mock_task_api_dep.get.return_value = {"id": 20, "name": "mum-user-update"}
    mock_task_api_dep.post.return_value = {"id": 200, "status": "RUNNING"}

    response = test_client.post(
        "/mum/ui/update-user",
        json={
            "target": "node-a",
            "username": "alice",
            "roles": ["readWrite"],
            "db": "admin",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert all(
        call.args[0] != "/nomad/variables/"
        for call in mock_task_api_dep.post.await_args_list
    )


@pytest.mark.usefixtures("mock_get_username_mapping")
def test_mum_update_user_with_password_uses_nomad_variable(
    test_client, mock_task_api_dep
):
    """Ensure update-user with password uses Nomad variable-backed config."""
    mock_task_api_dep.get.return_value = {"id": 20, "name": "mum-user-update"}
    mock_task_api_dep.post.side_effect = [
        {"path": "ignored"},
        {"id": 200, "status": "RUNNING"},
    ]

    response = test_client.post(
        "/mum/ui/update-user",
        json={
            "target": "node-a",
            "username": "alice",
            "password": "new-password",
            "roles": ["readWrite"],
            "db": "admin",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    variable_post = mock_task_api_dep.post.await_args_list[0]
    assert variable_post.args[0] == "/nomad/variables/"
    assert variable_post.kwargs["json"]["data"]["config"]["password"] == "new-password"

    execute_post = mock_task_api_dep.post.await_args_list[1]
    assert execute_post.args[0] == "/execute/mum-user-update"
    execute_meta = execute_post.kwargs["json"]["meta"]
    assert execute_meta["config_nomad_variable"].startswith("sep/runtime/mum/mum-")
    assert "config" not in execute_meta
    assert "new-password" not in json.dumps(execute_meta)
