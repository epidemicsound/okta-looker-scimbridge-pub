"""
Set of unit tests for app/app.py
"""

import pytest

from app.app import app, group_patch_ops
from app.appapi.appapi import AppAPIException, ObjectAlreadyExists

AUTH_HEADERS = {"Authorization": "Bearer test-token-12345"}


@pytest.fixture()
def client():
    """A mock Flask client"""
    app.config.update(
        {
            "TESTING": True,
        }
    )
    app.config["API_KEY"] = "test-token-12345"
    return app.test_client()


@pytest.fixture(autouse=True)
def mock_app_services(mocker):
    """Mocks the external services attached to the app object."""
    mocker.patch.object(app, "appapi", create=True)
    mocker.patch.object(app, "logger", create=True)
    mocker.patch.object(app, "db", create=True)


@pytest.fixture
def user_id():
    """A mock user id"""
    return "test-user-123"


@pytest.fixture
def user_name():
    """A mock username"""
    return "test.user@test"


@pytest.fixture
def group_name():
    """A mock group name"""
    return "Test Group 123"


@pytest.fixture
def group_id():
    """A mock group id"""
    return "test-group-id"


@pytest.fixture
def mock_user_db():
    """A mock User object from Firestore db"""
    return {
        "id": "test.user@test",
        "idp_id": "test.user@test",
    }


@pytest.fixture
def mock_user_response():
    """A mock SCIM User object"""
    return {
        "id": "test.user@test",
        "userName": "test.user@test",
        "displayName": "Test User",
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "name": {"givenName": "Test", "familyName": "User"},
        "emails": [{"primary": True, "value": "test.user@test", "type": "work"}],
        "locale": "en-US",
        "active": True,
    }


@pytest.fixture
def mock_group_response():
    """A mock SCIM Group object"""
    return {
        "id": "group-123",
        "displayName": "Updated Group Name",
        "members": [{"value": "user-1"}],
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
    }


@pytest.fixture
def mock_list_response_one_group(mock_group_response):
    """A mock SCIM ListResponse object containing a single group"""
    return {
        "Resources": [mock_group_response],
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "itemsPerPage": 1,
        "startIndex": 1,
        "totalResults": 1,
    }


@pytest.fixture
def mock_list_response_one_user(mock_user_response):
    """A mock SCIM ListResponse object containing a single user"""
    return {
        "Resources": [mock_user_response],
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "itemsPerPage": 1,
        "startIndex": 1,
        "totalResults": 1,
    }


def test_get_users_authorization_failure(client):
    """
    Tests the sucess path: GET /scim/v2/Users"
    - No Authorization header is provided
    - Expects an HTTP 401 Unauthorized
    """
    response = client.get("/scim/v2/Users")
    assert response.status_code == 401


def test_validation_empty_json(client):
    """
    Tests the failure path: POST /scim/v2/Users"
    - Payload is empty
    - Expects an HTTP 400 Bad Request
    """
    response = client.post("/scim/v2/Users", json={}, headers=AUTH_HEADERS)
    assert response.status_code == 400


def test_validation_invalid_payload(client):
    """
    Tests the failure path: POST /scim/v2/Users"
    - Payload is not a valid SCIM object
    - Expects an HTTP 400 Bad Request
    """
    payload = {"foo": "bar"}
    response = client.post("/scim/v2/Users", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 400


# Test SCIM GET /Users
def test_get_users_default_pagination(client, mock_user_response, mock_user_db):
    """
    Tests the sucess path: GET /scim/v2/Users"
    - Expects the app.appapi.get_users to be called.
    - externalIDs are found in the database and returned with the response
    - Expects an HTTP 200 response with a payload.
    """
    total_users = 1
    app.appapi.get_users.return_value = ([mock_user_response], total_users)
    app.db.find_user_by_id.return_value = mock_user_db

    response = client.get("/scim/v2/Users", headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.get_users.assert_called_once_with(100, 0)
    assert response.status_code == 200
    assert response_json["totalResults"] == total_users
    assert response_json["startIndex"] == 1
    assert response_json["itemsPerPage"] == 1
    assert response_json["Resources"] == [mock_user_response]


def test_get_users_nodatabase(client, mock_user_response):
    """
    Tests the sucess path: GET /scim/v2/Users"
    - Expects the app.appapi.get_users to be called.
    - externalID are not found in the database
    - Expects an HTTP 200 response with a payload.
    """
    total_users = 1
    app.appapi.get_users.return_value = ([mock_user_response], total_users)
    app.db.find_user_by_id.return_value = None

    response = client.get("/scim/v2/Users", headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.logger.info.assert_called_once_with(
        "Okta user ID not found in the database for user with Looker ID %s", mock_user_response["id"]
    )
    app.appapi.get_users.assert_called_once_with(100, 0)
    assert response.status_code == 200
    assert response_json["totalResults"] == total_users
    assert response_json["startIndex"] == 1
    assert response_json["itemsPerPage"] == 1
    assert response_json["Resources"] == [mock_user_response]


def test_get_users_custom_pagination(client, mock_user_db):
    """
    Tests the sucess path: GET /scim/v2/Users?startIndex=51&count=25"
    - Expects the app.appapi.get_users to be called with count=25 and startindex=50.
    - Expects an HTTP 200 response with a payload.
    """
    app.appapi.get_users.return_value = ([], 0)
    app.db.find_user_by_id.return_value = mock_user_db

    response = client.get("/scim/v2/Users?startIndex=51&count=25", headers=AUTH_HEADERS)

    app.appapi.get_users.assert_called_once_with(25, 50)
    assert response.status_code == 200


def test_get_users_with_valid_filter(client, user_name, mock_user_response, mock_list_response_one_user, mock_user_db):
    """
    Tests the sucess path: GET /scim/v2/Users?filter=userName eq "test.user@test"
    - Expects the app.appapi.search_users to be called.
    - Expects an HTTP 200 response with a payload.
    """
    app.appapi.search_users.return_value = ([mock_user_response], 1)
    app.db.find_user_by_id.return_value = mock_user_db

    response = client.get(f'/scim/v2/Users?filter=userName eq "{user_name}"', headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.search_users.assert_called_once_with(user_name)
    assert response.status_code == 200
    assert response_json == mock_list_response_one_user


def test_get_users_with_invalid_filter(client, user_name):
    """
    Tests the failure path: GET /scim/v2/Users?filter=userName gte "{user_name}"
    - Expects an HTTP 501 Not Implemented Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    response = client.get(f'/scim/v2/Users?filter=userName gte "{user_name}"', headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 501
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert "Unexpected filter:" in response_json["detail"]


def test_get_users_search_api_exception_filter(client, user_name):
    """
    Tests the failure path: GET /scim/v2/Users?filter=userName eq "test.user@test"
    - Expects the app.search_users.get_group to be called.
    - Expects app.appapi.search_users to raise AppAPIException.
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = f"Unexpected error when searching for user {user_name}"
    app.appapi.search_users.side_effect = AppAPIException(exception_message)

    response = client.get(f'/scim/v2/Users?filter=userName eq "{user_name}"', headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.search_users.assert_called_once()
    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert exception_message in response_json["detail"]


def test_get_users_search_api_exception(client):
    """
    Tests the failure path: GET /scim/v2/Users
    - Expects the app.appapi.get_users to be called.
    - Expects app.appapi.get_users to raise AppAPIException.
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = "Unexpected error when geting all users"
    app.appapi.get_users.side_effect = AppAPIException(exception_message)

    response = client.get("/scim/v2/Users", headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.get_users.assert_called_once()
    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert exception_message in response_json["detail"]


# Test SCIM user GET
def test_get_user_success(client, user_id, mock_user_response, mock_user_db):
    """
    Tests the success path: GET /scim/v2/Users/<id>
    - Expects the app.appapi.get_user to be called.
    - externalID is found in the database and returned with the response
    - Expects an HTTP 200 response with a payload.
    """
    app.appapi.get_user.return_value = mock_user_response
    app.db.find_user_by_id.return_value = mock_user_db

    response = client.get(f"/scim/v2/Users/{user_id}", headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 200
    assert response_json == mock_user_response


def test_get_user_success_no_database(client, user_id, mock_user_response):
    """
    Tests the success path: GET /scim/v2/Users/<id>
    - Expects the app.appapi.get_user to be called.
    - externalID is not found in the database
    - Expects an HTTP 200 response with a payload.
    """
    app.appapi.get_user.return_value = mock_user_response
    app.db.find_user_by_id.return_value = None

    response = client.get(f"/scim/v2/Users/{user_id}", headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.logger.info.assert_called_once_with(
        "Okta user ID not found in the database for user with Looker ID %s", mock_user_response["id"]
    )
    assert response.status_code == 200
    assert response_json == mock_user_response


def test_get_user_not_found(client, user_id):
    """
    Tests the not found path: GET /scim/v2/Users/<id>
    - Expects the app.appapi.get_user to be called.
    - Expects an HTTP 404 Not Found response.
    """
    app.appapi.get_user.return_value = None

    response = client.get(f"/scim/v2/Users/{user_id}", headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_get_user_failure(client, user_id):
    """
    Tests the failure path: GET /scim/v2/Users/<id>
    - Expects app.appapi.get_user to raise AppAPIException.
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = f"Unexpected error when retrieving user id:{user_id}"
    app.appapi.get_user.side_effect = AppAPIException(exception_message)

    response = client.get(f"/scim/v2/Users/{user_id}", headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 500
    assert exception_message in response_json["detail"]


def test_create_user_success(client, mock_user_response):
    """
    Tests the success path: POST /scim/v2/Users/
    - Expects the app.appapi.create_user to be called.
    - Expects an HTTP 204 No Content response.
    """
    app.appapi.create_user.return_value = mock_user_response

    response = client.post("/scim/v2/Users", json=mock_user_response, headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.create_user.assert_called_once()
    assert response.status_code == 201
    assert response_json == mock_user_response


def test_create_user_failure_already_exists(client, user_name, mock_user_response):
    """
    Tests the failure path: POST /scim/v2/Users/<id>
    - Expects app.appapi.create_user to raise ObjectAlreadyExists.
    - Expects an HTTP 409 Conflict Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = f"User {user_name} already exists"
    app.appapi.create_user.side_effect = ObjectAlreadyExists(exception_message)

    response = client.post("/scim/v2/Users", json=mock_user_response, headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 409
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 409
    assert exception_message in response_json["detail"]


def test_create_user_failure(client, user_name, mock_user_response):
    """
    Tests the failure path: POST /scim/v2/Users/<id>
    - Expects app.appapi.create_user to raise AppAPIException.
    - Expects an HTTP 500 response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = f"Unexpected error when creating user {user_name}"
    app.appapi.create_user.side_effect = AppAPIException(exception_message)

    response = client.post("/scim/v2/Users", json=mock_user_response, headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 500
    assert exception_message in response_json["detail"]


# Test SCIM user PUT
def test_update_user_success(client, user_id, mock_user_response):
    """
    Tests the success path: PUT /scim/v2/Users/<id>
    - Expects the app.appapi.get_user to be called.
    - Expects the app.appapi.update_user to be called.
    - Expects an HTTP 200 response.
    - Expects a SCIM-compliant JSON error body.
    - Expects user ID to be added to ID database
    """
    expected_return_payload = mock_user_response.copy()
    expected_return_payload["externalId"] = user_id
    app.appapi.get_user.return_value = mock_user_response
    app.appapi.update_user.return_value = expected_return_payload

    response = client.put(f"/scim/v2/Users/{user_id}", json=expected_return_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.get_user.assert_called_once_with(user_id)
    app.appapi.update_user.assert_called_once_with(user_id, expected_return_payload, mock_user_response["userName"])
    app.db.add_user.assert_called_once_with(user_id, expected_return_payload["externalId"])
    assert response.status_code == 200
    assert response_json == expected_return_payload


def test_update_user_deactivate(client, user_id, mock_user_response):
    """
    Tests the success path: PUT /scim/v2/Users/<id>
    - Expects the app.appapi.get_user to be called.
    - Expects the app.appapi.update_user to be called.
    - Expects an HTTP 200 response.
    - Expects a SCIM-compliant JSON error body.
    - Expects user ID to be removed from ID database
    """
    expected_return_payload = mock_user_response.copy()
    expected_return_payload["externalId"] = "test.user@test"
    expected_return_payload["active"] = False
    app.appapi.get_user.return_value = mock_user_response
    app.appapi.update_user.return_value = expected_return_payload

    response = client.put(f"/scim/v2/Users/{user_id}", json=expected_return_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.get_user.assert_called_once_with(user_id)
    app.appapi.update_user.assert_called_once_with(user_id, expected_return_payload, mock_user_response["userName"])
    app.db.remove_user.assert_called_once_with(user_id)

    assert response.status_code == 200
    assert response_json == expected_return_payload


def test_update_user_not_found(client, user_id, mock_user_response):
    """
    Tests the not found path: PUT /scim/v2/Users/<id>
    - Expects the app.appapi.get_user to be called.
    - Expects an HTTP 404 Not Found response.
    """
    expected_return_payload = mock_user_response.copy()
    expected_return_payload["externalId"] = "test.user@test"
    app.appapi.get_user.return_value = None

    response = client.put(f"/scim/v2/Users/{user_id}", json=expected_return_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 404
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]


def test_update_user_retrive_failure(client, user_id, mock_user_response):
    """
    Tests the failure path: PUT /scim/v2/Users/<id>
    - Expects app.appapi.get_user to raise AppAPIException.
    - Expects an HTTP 500 response.
    - Expects a SCIM-compliant JSON error body.
    """
    expected_return_payload = mock_user_response.copy()
    expected_return_payload["externalId"] = "test.user@test"
    exception_message = f"Unexpected error when retriving user id:{user_id}"
    app.appapi.get_user.side_effect = AppAPIException(exception_message)

    response = client.put(f"/scim/v2/Users/{user_id}", json=expected_return_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 500
    assert exception_message in response_json["detail"]


def test_update_user_update_failure(client, user_id, mock_user_response):
    """
    Tests the failure path: PUT /scim/v2/Users/<id>
    - Expects the app.appapi.get_user to be called.
    - Expects app.appapi.update_user to raise AppAPIException.
    - Expects an HTTP 500 response.
    - Expects a SCIM-compliant JSON error body.
    """
    expected_return_payload = mock_user_response.copy()
    expected_return_payload["externalId"] = "test.user@test"
    exception_message = f"Unexpected error when updating user id:{user_id}"
    app.appapi.update_user.side_effect = AppAPIException(exception_message)

    response = client.put(f"/scim/v2/Users/{user_id}", json=expected_return_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 500
    assert exception_message in response_json["detail"]


# Test SCIM user PATCH
def test_patch_user_success(client, user_id, mock_user_response):
    """
    Tests the success path: PATCH /scim/v2/Users/<id>
    - Expects app.appapi.change_user_state to be called
    - Expects an HTTP 200 response.
    - Expects a SCIM-compliant JSON error body.
    """
    expected_return_payload = mock_user_response.copy()
    expected_return_payload["active"] = False
    payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "value": {"active": False}}],
    }
    app.appapi.change_user_state.return_value = expected_return_payload

    response = client.patch(f"/scim/v2/Users/{user_id}", json=payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.db.remove_user.assert_called_once_with(user_id)
    assert response.status_code == 200
    assert response_json == expected_return_payload


def test_patch_user_update_failure(client, user_id):
    """
    Tests the failure path: PATCH /scim/v2/Users/<id>
    - Expects app.appapi.change_user_state to raise AppAPIException.
    - Expects an HTTP 500 response.
    - Expects a SCIM-compliant JSON error body.
    """
    payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "value": {"active": False}}],
    }
    exception_message = f"Unexpected error when patching user id:{user_id}"
    app.appapi.change_user_state.side_effect = AppAPIException(exception_message)

    response = client.patch(f"/scim/v2/Users/{user_id}", json=payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 500
    assert exception_message in response_json["detail"]


def test_patch_user_unsuppored_operation(client, user_id):
    """
    Tests the failure path: PATCH /scim/v2/Users/<id>
    - Expects an HTTP 501 Not Implemented response.
    - Expects a SCIM-compliant JSON error body.
    """
    payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "remove", "path": "nickName"}],
    }
    exception_message = "SCIM PATCH method remove not implemented"
    response = client.patch(f"/scim/v2/Users/{user_id}", json=payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 501
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert exception_message in response_json["detail"]


def test_patch_user_unsupported_password_change(client, user_id, mock_user_response):
    """
    Tests the success path: PATCH /scim/v2/Users/<id>
    - Expects an HTTP 501 response.
    - Expects a SCIM-compliant JSON error body.
    - Situation is logged as an error
    """
    payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "value": {"password": "abraka"}}],
    }
    app.appapi.get_user.return_value = mock_user_response

    response = client.patch(f"/scim/v2/Users/{user_id}", json=payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.logger.error.assert_called_once()
    assert response.status_code == 501
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]


# Test SCIM user DELETE
def test_delete_user_success(client, user_id):
    """
    Tests the success path: DELETE /scim/v2/Users/<id>
    - Expects the app.appapi.delete_user to be called.
    - Expects an HTTP 204 No Content response.
    """
    response = client.delete(f"/scim/v2/Users/{user_id}", headers=AUTH_HEADERS)

    app.db.remove_user.assert_called_once_with(user_id)
    assert response.status_code == 204
    assert response.data == b""


def test_delete_user_failure(client, user_id):
    """
    Tests the failure path: DELETE /scim/v2/Groups/<id>
    - Expects app.appapi.delete_user to raise AppAPIException.
    - Expects an HTTP 404 Not Found response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = f"Failed to delete the user {user_id}. Perhaps it is no longer there"
    app.appapi.delete_user.side_effect = AppAPIException(exception_message)

    response = client.delete(f"/scim/v2/Users/{user_id}", headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.db.remove_user.assert_called_once_with(user_id)
    assert response.status_code == 404
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 404
    assert exception_message in response_json["detail"]


# Test SCIM group CREATE
def test_create_group_success(client, mock_group_response):
    """
    Tests the success path: POST /scim/v2/Groups/
    - Expects the app.appapi.create_group to be called.
    - Expects the app.appapie.update_group_membership to be called
    - Expects an HTTP 204 No Content response.
    """
    create_payload = {"displayName": "Updated Group Name", "members": [{"value": "user-1"}]}
    app.appapi.update_group_membership.return_value = mock_group_response

    response = client.post("/scim/v2/Groups", json=create_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.update_group_membership.assert_called_once()
    assert response.status_code == 201
    assert response_json == mock_group_response


def test_create_group_failure(client, group_name):
    """
    Tests the failure path: POST /scim/v2/Groups/<id>
    - Expects app.appapi.create_group to raise AppAPIException.
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    create_payload = {"displayName": group_name}
    exception_message = f"Unexpected error when creating group {group_name}"
    app.appapi.create_group.side_effect = AppAPIException(exception_message)

    response = client.post("/scim/v2/Groups", json=create_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 500
    assert exception_message in response_json["detail"]


# Test SCIM groupS GET
def test_get_groups_default_pagination(client, mock_group_response):
    """
    Tests the sucess path: GET /scim/v2/Groups"
    - Expects the app.appapi.get_groups to be called.
    - Expects an HTTP 200 response with a payload.
    """
    total_groups = 1
    app.appapi.get_groups.return_value = ([mock_group_response], total_groups)

    response = client.get("/scim/v2/Groups", headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.get_groups.assert_called_once_with(100, 0)
    assert response.status_code == 200
    assert response_json["totalResults"] == total_groups
    assert response_json["startIndex"] == 1
    assert response_json["itemsPerPage"] == 1
    assert response_json["Resources"] == [mock_group_response]


def test_get_groups_custom_pagination(client):
    """
    Tests the sucess path: GET /scim/v2/Groups?startIndex=51&count=25"
    - Expects the app.appapi.get_groups to be called.
    - Expects an HTTP 200 response with a payload.
    """
    app.appapi.get_groups.return_value = ([], 0)

    response = client.get("/scim/v2/Groups?startIndex=51&count=25", headers=AUTH_HEADERS)

    app.appapi.get_groups.assert_called_once_with(25, 50)
    assert response.status_code == 200


def test_get_groups_with_valid_filter(client, group_name, mock_group_response, mock_list_response_one_group):
    """
    Tests the sucess path: GET /scim/v2/Groups?filter=displayName eq "test-group-123"
    - Expects the app.appapi.search_groups to be called.
    - Expects an HTTP 200 response with a payload.
    """
    app.appapi.search_groups.return_value = ([mock_group_response], 1)

    response = client.get(f'/scim/v2/Groups?filter=displayName eq "{group_name}"', headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.search_groups.assert_called_once_with(group_name)
    assert response.status_code == 200
    assert response_json == mock_list_response_one_group


def test_get_groups_with_invalid_filter(client, group_name):
    """
    Tests the failure path: GET /scim/v2/Groups?filter=displayName gt "test-group-123"
    - Expects an HTTP 501 Not Implemented Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    response = client.get(f'/scim/v2/Groups?filter=displayName gte "{group_name}"', headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 501
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert "Unexpected filter:" in response_json["detail"]


def test_get_groups_search_api_exception_filter(client, group_name):
    """
    Tests the failure path: GET /scim/v2/Groups?filter=displayName eq "test-group-123"
    - Expects the app.search_groups.get_group to be called.
    - Expects app.appapi.search_groups to raise AppAPIException.
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = f"Unexpected error when searching for group {group_name}"
    app.appapi.search_groups.side_effect = AppAPIException(exception_message)

    response = client.get(f'/scim/v2/Groups?filter=displayName eq "{group_name}"', headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.search_groups.assert_called_once()
    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert exception_message in response_json["detail"]


def test_get_groups_search_api_exception(client):
    """
    Tests the failure path: GET /scim/v2/Groups
    - Expects the app.search_groups.get_group to be called.
    - Expects app.appapi.get_groups to raise AppAPIException.
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = "Unexpected error when retrieving groups"
    app.appapi.get_groups.side_effect = AppAPIException(exception_message)

    response = client.get("/scim/v2/Groups", headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.get_groups.assert_called_once()
    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert exception_message in response_json["detail"]


# Test SCIM group GET
def test_get_group_success(client, group_id, mock_group_response):
    """
    Tests the success path: GET /scim/v2/Groups/<id>
    - Expects the app.appapi.get_group to be called.
    - Expects an HTTP 200 response with a payload.
    """
    app.appapi.get_group.return_value = mock_group_response

    response = client.get(f"/scim/v2/Groups/{group_id}", headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 200
    assert response_json == mock_group_response


def test_get_group_not_found(client, group_id):
    """
    Tests the not found path: GET /scim/v2/Groups/<id>
    - Expects the app.appapi.get_group to be called.
    - Expects an HTTP 404 No Content response.
    """
    app.appapi.get_group.return_value = None

    response = client.get(f"/scim/v2/Groups/{group_id}", headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_get_group_failure(client, group_id):
    """
    Tests the failure path: GET /scim/v2/Groups/<id>
    - Expects app.appapi.get_group to raise AppAPIException.
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = f"Unexpected error when retrieving group id:{group_id}"
    app.appapi.get_group.side_effect = AppAPIException(exception_message)

    response = client.get(f"/scim/v2/Groups/{group_id}", headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 500
    assert exception_message in response_json["detail"]


# Test SCIM group PATCH and PUT
def test_group_update_put(client, group_id, mock_group_response):
    """
    Tests the success path: PUT /scim/v2/Groups/<id>
    - Expects app.appapi.update_group_name to to be called
    - Expects app.appapi.update_group_membership to to be called
    - Expects an HTTP 200 response with a payload.
    """
    put_payload = {"displayName": "Updated Group Name", "members": [{"value": "user-1"}]}
    app.appapi.get_group.return_value = mock_group_response

    response = client.put(f"/scim/v2/Groups/{group_id}", json=put_payload, headers=AUTH_HEADERS)

    app.appapi.update_group_name.assert_called_once_with(group_id, put_payload["displayName"])
    app.appapi.update_group_membership.assert_called_once_with(group_id, put_payload["members"])
    assert response.status_code == 200
    assert response.get_json() == mock_group_response


def test_group_patch(client, group_id, mock_group_response, mocker):
    """
    Tests the success path: PATCH /scim/v2/Groups/<id>
    - Expects app.group_patch_ops to to be called
    - Expects app.appapi.update_group_membership to to be called
    - Expects an HTTP 200 response with a payload.
    """
    patch_payload = {"Operations": [{"op": "replace", "path": "displayName", "value": "New Name"}]}
    mock_group_patch_ops = mocker.patch("app.app.group_patch_ops", return_value=(None, 0))
    app.appapi.get_group.return_value = mock_group_response

    response = client.patch(f"/scim/v2/Groups/{group_id}", json=patch_payload, headers=AUTH_HEADERS)

    mock_group_patch_ops.assert_called_once()
    assert response.status_code == 200
    assert response.get_json() == mock_group_response


def test_group_patch_failure(client, group_id, mocker):
    """
    Tests the failure path: PATCH /scim/v2/Groups/<id>
    - Expects app.appapi.get_group to raise AppAPIException exception
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    patch_payload = {"Operations": [{"op": "replace", "path": "displayName", "value": "New Name"}]}
    exception_message = f"Unexpected error when updating group id:{group_id}"
    mock_group_patch_ops = mocker.patch("app.app.group_patch_ops", return_value=(None, 0))
    app.appapi.get_group.side_effect = AppAPIException(exception_message)

    response = client.patch(f"/scim/v2/Groups/{group_id}", json=patch_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    mock_group_patch_ops.assert_called_once()
    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert exception_message in response_json["detail"]


def test_group_patch_patchops_failure(client, group_id, mocker):
    """
    Tests the failure path: PATCH /scim/v2/Groups/<id>
    - Expects app.group_patch_ops to return an error
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    patch_payload = {"Operations": [{"op": "replace", "path": "displayName", "value": "New Name"}]}
    mock_group_patch_ops = mocker.patch("app.app.group_patch_ops", return_value=("Some error", 500))

    response = client.patch(f"/scim/v2/Groups/{group_id}", json=patch_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    mock_group_patch_ops.assert_called_once()
    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert "Some error" in response_json["detail"]


def test_group_update_put_failure(client, group_id):
    """
    Tests the failure path: PUT /scim/v2/Groups/<id>
    - Expects app.appapi.update_group_name to raise AppAPIException exception
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    put_payload = {"displayName": "Updated Group Name", "members": [{"value": "user-1"}]}
    exception_message = f"Unexpected error when updating group id:{group_id}"
    app.appapi.update_group_name.side_effect = AppAPIException(exception_message)

    response = client.put(f"/scim/v2/Groups/{group_id}", json=put_payload, headers=AUTH_HEADERS)
    response_json = response.get_json()

    app.appapi.update_group_name.assert_called_once()
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 500
    assert exception_message in response_json["detail"]


def test_group_patch_ops_members(group_id):
    """
    Process expected PATCH operations without failing
    - Expects nothing to be returned from group_patch_ops function
    """
    operations = [
        {
            "op": "remove",
            "path": 'members[value eq "89bb1940-b905-4575-9e7f-6f887cfb368e"]',
        },
        {
            "op": "add",
            "path": "members",
            "value": [
                {
                    "value": "23a35c27-23d3-4c03-b4c5-6443c09e7173",
                    "display": "test.user@test",
                }
            ],
        },
        {
            "op": "replace",
            "path": "members",
            "value": [
                {
                    "value": "23a35c27-23d3-4c03-b4c5-6443c09e7173",
                    "display": "test.user@test",
                },
                {
                    "value": "89bb1940-b905-4575-9e7f-6f887cfb368e",
                    "display": "test.user@test",
                },
            ],
        },
    ]

    result = group_patch_ops(group_id, operations)

    app.appapi.update_group_membership.assert_called_once()
    app.appapi.add_group_member.assert_called_once_with(group_id, user_id="23a35c27-23d3-4c03-b4c5-6443c09e7173")
    app.appapi.remove_group_member.assert_called_once_with(group_id, "89bb1940-b905-4575-9e7f-6f887cfb368e")
    assert result == (None, None)


def test_group_patch_ops_group_rename(group_id):
    """
    Process group rename PATCH operation without failing
    - Expects nothing to be returned from group_patch_ops function
    """
    operations = [
        {"op": "replace", "value": {"id": "abf4dd94-a4c0-4f67-89c9-76b03340cb9b", "displayName": "Test SCIMv2"}}
    ]

    result = group_patch_ops(group_id, operations)

    app.appapi.update_group_name.assert_called_once_with(group_id, "Test SCIMv2")
    assert result == (None, None)


def test_group_patch_ops_remove_unsupported_filter(group_id):
    """
    Use unsupported filter in user group membership removal operation
    - Expects 501 error code returned by group_patch_ops function
    """
    operations = [
        {
            "op": "remove",
            "path": 'members[value sw "foobar"]',
        }
    ]

    result = group_patch_ops(group_id, operations)

    assert result[1] == 501


# Test SCIM group DELETE
def test_delete_group_success(client, group_id):
    """
    Tests the success path: DELETE /scim/v2/Groups/<id>
    - Expects the app.appapi.delete_group to be called.
    - Expects an HTTP 204 No Content response.
    """
    response = client.delete(f"/scim/v2/Groups/{group_id}", headers=AUTH_HEADERS)

    assert response.status_code == 204
    assert response.data == b""


def test_delete_group_failure(client, group_id):
    """
    Tests the failure path: DELETE /scim/v2/Groups/<id>
    - Expects app.appapi.delete_group to raise AppAPIException.
    - Expects an HTTP 500 Internal Server Error response.
    - Expects a SCIM-compliant JSON error body.
    """
    exception_message = f"Unable to delete group id:{group_id}"
    app.appapi.delete_group.side_effect = AppAPIException(exception_message)

    response = client.delete(f"/scim/v2/Groups/{group_id}", headers=AUTH_HEADERS)
    response_json = response.get_json()

    assert response.status_code == 500
    assert response_json["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert response_json["status"] == 500
    assert exception_message in response_json["detail"]
