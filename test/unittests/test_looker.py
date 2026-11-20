"""
Set of unit tests for appappi/looker.py
"""

import logging

import looker_sdk
import pytest

from app.appapi.appapi import AppAPIException, ObjectAlreadyExists
from app.appapi.looker import LookerAPI, handle_sdk_errors


# Tests for handle_sdk_errors - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def test_handle_sdk_errors_no_error():
    """
    Tests that the decorator returns the function's result when no exception is raised.
    """

    @handle_sdk_errors
    def success_function():
        return "it worked"

    assert success_function() == "it worked"


def test_handle_sdk_errors_catches_sdk_error():
    """
    Tests that the decorator catches SDKError and raises AppAPIException.
    """
    original_error_message = "Original SDK failure"

    @handle_sdk_errors
    def sdk_error_function():
        raise looker_sdk.error.SDKError(message=original_error_message)

    with pytest.raises(AppAPIException) as exc_info:
        sdk_error_function()

    expected_message = f"An unexpected Looker API error occurred: {original_error_message}"
    assert str(exc_info.value) == expected_message

    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, looker_sdk.error.SDKError)


def test_handle_sdk_errors_ignores_other_errors():
    """
    Tests that the decorator does NOT catch other types of exceptions (e.g., ValueError).
    """

    @handle_sdk_errors
    def other_error_function():
        raise ValueError("This is a different error")

    with pytest.raises(ValueError) as exc_info:
        other_error_function()

    assert str(exc_info.value) == "This is a different error"


def test_handle_sdk_errors_preserves_metadata():
    """
    Tests that the decorator preserves the original function's name and docstring.
    """

    @handle_sdk_errors
    def function_with_metadata():
        """This is the docstring."""

    assert function_with_metadata.__name__ == "function_with_metadata"
    assert function_with_metadata.__doc__ == "This is the docstring."


# Sample data for LookerAPI users tests - - - - - - - - - - - - - - - - - - - - - - - - -
@pytest.fixture
def sample_username():
    """Provides a sample username."""

    return "jane.doe@test"


@pytest.fixture
def sample_looker_user():
    """Provides a sample looker_sdk.models40.User object."""

    return looker_sdk.models40.User(
        display_name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        is_disabled=False,
        locale="en_US",
        id=123,
        email="jane.doe@test",
    )


@pytest.fixture
def user_scim_payload():
    """Provides SCIM payload dictionary for a user."""
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": 123,
        "userName": "jane.doe@test",
        "name": {"givenName": "Jane", "familyName": "Doe"},
        "emails": [{"primary": True, "value": "jane.doe@test", "type": "work"}],
        "displayName": "Jane Doe",
        "locale": "en_US",
        "active": True,
        "meta": {"resourceType": "User"},
    }


@pytest.fixture
def mocked_looker_api(mocker):
    """
    Provides an initialized LookerAPI instance with a mocked SDK
    and a mocked logger.
    """

    mocker.patch("app.appapi.looker.looker_sdk.init40")
    mock_logger = mocker.Mock(spec=logging.Logger)
    return LookerAPI(logger=mock_logger)


# LookerAPI tests - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def test_create_user_scim_payload(mocked_looker_api, sample_looker_user, user_scim_payload):
    """
    Test create_user_scim_payload with sample data.
    """
    scim_user_payload = mocked_looker_api.create_user_scim_payload(sample_looker_user)
    assert scim_user_payload == user_scim_payload


def test_create_user_scim_payload_custom_email(mocked_looker_api, sample_looker_user, user_scim_payload):
    """
    Test create_user_scim_payload with sample data but custom email.
    """
    custom_email = "custom@test"
    scim_user_payload = mocked_looker_api.create_user_scim_payload(sample_looker_user, email=custom_email)
    customized_expected_scim_dict = user_scim_payload
    customized_expected_scim_dict["userName"] = custom_email
    customized_expected_scim_dict["emails"][0]["value"] = custom_email
    assert scim_user_payload == customized_expected_scim_dict


def test_create_user(mocked_looker_api, sample_looker_user, user_scim_payload, sample_username):
    """
    Test create_user expecting it to succeed.
    """

    mocked_looker_api.sdk.search_users.return_value = []
    mocked_looker_api.sdk.create_user.return_value = sample_looker_user
    mocked_looker_api.sdk.create_user_credentials_email.return_value = None

    n_user_scim = mocked_looker_api.create_user(user_scim_payload, sample_username)
    assert user_scim_payload == n_user_scim


def test_create_user_already_exists(mocked_looker_api, sample_looker_user, user_scim_payload, sample_username):
    """
    Test create_user when the username is already taken.
    """

    mocked_looker_api.sdk.search_users.return_value = [sample_looker_user]

    with pytest.raises(
        ObjectAlreadyExists,
        match=f"User with {sample_username} username already exists",
    ):
        mocked_looker_api.create_user(user_scim_payload, sample_username)


def test_delete_user(mocked_looker_api):
    """
    Test delete_user.
    """
    mocked_looker_api.sdk.delete_user.return_value = None
    mocked_looker_api.delete_user(user_id="123")


def test_get_user(mocked_looker_api, sample_looker_user, user_scim_payload):
    """
    Test get_user. Expect success
    """
    mocked_looker_api.sdk.user.return_value = sample_looker_user
    g_user_scim = mocked_looker_api.get_user(user_id="123")

    assert g_user_scim == user_scim_payload


def test_get_user_not_exists(mocked_looker_api):
    """
    Test get_user when the user does not exist
    """
    error_title = "Looker Not Found (404)"
    mock_404_error = looker_sdk.error.SDKError(message=f"<html><head><title>{error_title}</title></head></html>")
    mocked_looker_api.sdk.user.side_effect = mock_404_error

    g_user_scim = mocked_looker_api.get_user(user_id="123")

    assert g_user_scim is None


def test_get_user_unexpected_error(mocked_looker_api):
    """
    Test get_user with unexpected failure
    """
    mock_404_error = looker_sdk.error.SDKError(message="<html><head><title>Something else</title></head></html>")
    mocked_looker_api.sdk.user.side_effect = mock_404_error

    with pytest.raises(AppAPIException):
        mocked_looker_api.get_user(user_id="123")


def test_get_users_zero_users(mocker, mocked_looker_api):
    """
    Test get_users with the number of users being zero
    """

    test_limit = 50
    test_offset = 0
    mocked_looker_api.sdk.all_users.return_value = []
    users, total = mocked_looker_api.get_users(limit=test_limit, offset=test_offset)

    assert total == 0
    assert len(users) == 0
    assert users == []

    expected_calls = [
        mocker.call(limit=100, offset=0, sorts="id", fields="id"),
        mocker.call(limit=test_limit, offset=test_offset, sorts="id"),
    ]
    mocked_looker_api.sdk.all_users.assert_has_calls(expected_calls)
    assert mocked_looker_api.sdk.all_users.call_count == len(expected_calls)


def test_get_users_small_page(mocker, mocked_looker_api, sample_looker_user):
    """
    Test get_users with the number of users being lower than one page limit
    """
    test_limit = 10
    test_offset = 0
    mock_users = [sample_looker_user] * 5

    mocked_looker_api.sdk.all_users.side_effect = [
        mock_users,
        [],
        mock_users,
    ]

    users, total = mocked_looker_api.get_users(limit=test_limit, offset=test_offset)

    assert total == 5
    assert len(users) == 5

    expected_calls = [
        mocker.call(limit=100, offset=0, sorts="id", fields="id"),
        mocker.call(limit=100, offset=100, sorts="id", fields="id"),
        mocker.call(limit=test_limit, offset=test_offset, sorts="id"),
    ]
    mocked_looker_api.sdk.all_users.assert_has_calls(expected_calls)
    assert mocked_looker_api.sdk.all_users.call_count == 3


def test_get_users_one_page(mocker, mocked_looker_api, sample_looker_user):
    """
    Test get_users with the number of users being exactly one page
    """
    test_limit = 10
    test_offset = 0
    mock_users = [sample_looker_user] * 10

    mocked_looker_api.sdk.all_users.side_effect = [
        mock_users,
        [],
        mock_users,
    ]

    users, total = mocked_looker_api.get_users(limit=test_limit, offset=test_offset)

    assert total == 10
    assert len(users) == 10

    expected_calls = [
        mocker.call(limit=100, offset=0, sorts="id", fields="id"),
        mocker.call(limit=100, offset=100, sorts="id", fields="id"),
        mocker.call(limit=test_limit, offset=test_offset, sorts="id"),
    ]
    mocked_looker_api.sdk.all_users.assert_has_calls(expected_calls)
    assert mocked_looker_api.sdk.all_users.call_count == len(expected_calls)


def test_get_users_many_pages(mocker, mocked_looker_api, sample_looker_user):
    """
    Test get_users with the number of users being more than one page
    """
    test_limit = 10
    test_offset = 30
    mock_users = [sample_looker_user] * 10
    mock_users_page1 = [sample_looker_user] * 100
    mock_users_page2 = [sample_looker_user] * 100
    mock_users_page3 = [sample_looker_user] * 18

    mocked_looker_api.sdk.all_users.side_effect = [
        mock_users_page1,
        mock_users_page2,
        mock_users_page3,
        [],
        mock_users,
    ]

    users, total = mocked_looker_api.get_users(limit=test_limit, offset=test_offset)

    assert total == 218
    assert len(users) == 10

    expected_calls = [
        mocker.call(limit=100, offset=0, sorts="id", fields="id"),
        mocker.call(limit=100, offset=100, sorts="id", fields="id"),
        mocker.call(limit=100, offset=200, sorts="id", fields="id"),
        mocker.call(limit=100, offset=300, sorts="id", fields="id"),
        mocker.call(limit=test_limit, offset=test_offset, sorts="id"),
    ]
    mocked_looker_api.sdk.all_users.assert_has_calls(expected_calls)
    assert mocked_looker_api.sdk.all_users.call_count == len(expected_calls)


def test_search_users_zero(mocked_looker_api, sample_username):
    """
    Test search_users with the number of users being zero
    """
    mocked_looker_api.sdk.search_users.return_value = []
    users, num_of_users = mocked_looker_api.search_users(email=sample_username)
    assert users == []
    assert num_of_users == 0


def test_search_users_one(mocked_looker_api, sample_looker_user, sample_username, user_scim_payload):
    """
    Test search_users with the number of users being one
    """
    mocked_looker_api.sdk.search_users.return_value = [sample_looker_user]
    users, num_of_users = mocked_looker_api.search_users(email=sample_username)
    assert users == [user_scim_payload]
    assert num_of_users == 1


def test_search_users_two(mocked_looker_api, sample_looker_user, sample_username):
    """
    Test search_users with the number of users being two. Should throw an exception
    """
    mocked_looker_api.sdk.search_users.return_value = [
        sample_looker_user,
        sample_looker_user,
    ]

    with pytest.raises(
        AppAPIException,
        match=f"Found more than one user with email:{sample_username}",
    ):
        mocked_looker_api.search_users(email=sample_username)


def test_change_user_state_deactivate(mocked_looker_api, sample_looker_user, user_scim_payload):
    """
    Test change_user_state by deactivating a user
    """
    sample_looker_user.is_disabled = True
    mocked_looker_api.sdk.update_user.return_value = sample_looker_user
    d_user_scim = mocked_looker_api.change_user_state(user_id=123, is_active=False)
    user_scim_payload["active"] = False

    assert d_user_scim == user_scim_payload


def test_change_user_state_activate_active(mocked_looker_api, sample_looker_user, user_scim_payload):
    """
    Test change_user_state by activating an already active user
    """
    mocked_looker_api.sdk.update_user.return_value = sample_looker_user
    d_user_scim = mocked_looker_api.change_user_state(user_id=123, is_active=True)

    assert d_user_scim == user_scim_payload


def test_update_user_locale(mocked_looker_api, sample_looker_user, sample_username, user_scim_payload):
    """
    Test update_user by changing locale
    """
    sample_looker_user.locale = "en_GB"
    user_scim_payload["locale"] = "en_GB"
    mocked_looker_api.sdk.update_user.return_value = sample_looker_user
    mocked_looker_api.sdk.update_user_credentials_email.return_value = None

    u_user_scim = mocked_looker_api.update_user(user_id=123, raw_user=user_scim_payload, username=sample_username)

    assert u_user_scim == user_scim_payload


def test_update_user_rename(mocked_looker_api, sample_looker_user, user_scim_payload):
    """
    Test update_user by changing the last name and username/email
    """
    sample_looker_user.last_name = "Smith"
    sample_looker_user.display_name = "Jane Smith"
    sample_looker_user.email = "jane.doe@test"

    user_scim_payload["userName"] = "jane.smith@test"
    user_scim_payload["emails"][0]["value"] = "jane.smith@test"
    user_scim_payload["name"]["familyName"] = "Smith"
    user_scim_payload["displayName"] = "Jane Smith"

    new_username = "jane.smith@test"

    mocked_looker_api.sdk.update_user.return_value = sample_looker_user
    mocked_looker_api.sdk.update_user_credentials_email.return_value = None

    u_user_scim = mocked_looker_api.update_user(user_id=123, raw_user=user_scim_payload, username=new_username)

    assert u_user_scim == user_scim_payload


# Sample data for LookerAPI group tests - - - - - - - - - - - - - - - - - - - - - - - - -
@pytest.fixture
def sample_groupname():
    """Provides a sample group name."""

    return "TestGroup"


@pytest.fixture
def sample_looker_group():
    """Provides a sample looker_sdk.models40.Group object."""

    return looker_sdk.models40.Group(
        name="TestGroup",
        id=987,
    )


@pytest.fixture
def group_scim_payload():
    """Provides SCIM payload dictionary for a group with no members."""
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "id": 987,
        "displayName": "TestGroup",
        "members": [],
        "meta": {"resourceType": "Group"},
    }


# LookerAPI group tests - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def test_add_group_member(mocked_looker_api, user_scim_payload):
    """
    Test add_group_member by adding an existing user
    """
    mocked_looker_api.sdk.add_group_user.return_value = None
    mocked_looker_api.sdk.get_user.return_value = user_scim_payload

    mocked_looker_api.add_group_member(group_id=987, user_id=123)


def test_add_group_member_nonexistent(mocked_looker_api):
    """
    Test add_group_member by adding an existing user
    """
    error_title = "Looker Not Found (404)"
    mock_404_error = looker_sdk.error.SDKError(message=f"<html><head><title>{error_title}</title></head></html>")
    mocked_looker_api.sdk.user.side_effect = mock_404_error

    mocked_looker_api.add_group_member(group_id=987, user_id=123)


def test_create_group(mocked_looker_api, sample_looker_group, sample_groupname, group_scim_payload):
    """
    Test create_group with no complications
    """
    mocked_looker_api.sdk.search_groups.return_value = []
    mocked_looker_api.sdk.create_group.return_value = sample_looker_group
    c_group_scim = mocked_looker_api.create_group(group_name=sample_groupname)

    assert c_group_scim == group_scim_payload


def test_create_group_already_exixts(mocked_looker_api, sample_looker_group, sample_groupname, group_scim_payload):
    """
    Test create_group when the group already exists
    """
    mocked_looker_api.sdk.search_groups.return_value = [sample_looker_group]
    c_group_scim = mocked_looker_api.create_group(group_name=sample_groupname)

    assert c_group_scim == group_scim_payload


def test_delete_group(mocked_looker_api):
    """
    Test delete_group.
    """
    mocked_looker_api.sdk.delete_group.return_value = None
    mocked_looker_api.delete_group(group_id="987")


def test_get_group(mocked_looker_api, sample_looker_group, group_scim_payload):
    """
    Test get_group. Zero members Expect success
    """
    mocked_looker_api.sdk.group.return_value = sample_looker_group
    mocked_looker_api.sdk.all_group_users.return_value = []

    g_group_scim = mocked_looker_api.get_group(group_id="987")

    assert g_group_scim == group_scim_payload


def test_get_group_one_page_members(mocked_looker_api, sample_looker_group, group_scim_payload, sample_looker_user):
    """
    Test get_group. Members fit on a single page (no pagination).
    """
    mock_members_page1 = [sample_looker_user] * 5
    mocked_looker_api.sdk.group.return_value = sample_looker_group
    mocked_looker_api.sdk.all_group_users.side_effect = [
        mock_members_page1,
        [],
    ]
    g_group_scim = mocked_looker_api.get_group(group_id="987")

    member_record = {
        'display': 'jane.doe@test',
        'value': 123,
    }
    members = [member_record] * 5
    group_scim_payload["members"] = members

    assert g_group_scim == group_scim_payload


def test_get_group_multiple_pages_members(mocked_looker_api, sample_looker_group, group_scim_payload, sample_looker_user):
    """
    Test get_group. Members would be retrieved by multiple API calls (pagination)
    """
    mock_members_page1 = [sample_looker_user] * 255
    mocked_looker_api.sdk.group.return_value = sample_looker_group
    mocked_looker_api.sdk.all_group_users.side_effect = [
        mock_members_page1,
        [],
    ]
    g_group_scim = mocked_looker_api.get_group(group_id="987")

    member_record = {
        'display': 'jane.doe@test',
        'value': 123,
    }
    members = [member_record] * 255
    group_scim_payload["members"] = members

    assert g_group_scim == group_scim_payload


def test_get_group_not_exists(mocked_looker_api):
    """
    Test get_group when the group does not exist
    """
    error_title = "Looker Not Found (404)"
    mock_404_error = looker_sdk.error.SDKError(message=f"<html><head><title>{error_title}</title></head></html>")
    mocked_looker_api.sdk.group.side_effect = mock_404_error

    g_group_scim = mocked_looker_api.get_group(group_id="987")

    assert g_group_scim is None


def test_get_group_unexpected_error(mocked_looker_api):
    """
    Test get_group with unexpected failure
    """
    mock_404_error = looker_sdk.error.SDKError(message="<html><head><title>Something else</title></head></html>")
    mocked_looker_api.sdk.group.side_effect = mock_404_error

    with pytest.raises(AppAPIException):
        mocked_looker_api.get_group(group_id="987")


def test_get_groups_zero_groups(mocker, mocked_looker_api):
    """
    Test get_groups with the number of groups being zero
    """

    test_limit = 50
    test_offset = 0
    mocked_looker_api.sdk.all_groups.return_value = []
    groups, total = mocked_looker_api.get_groups(limit=test_limit, offset=test_offset)

    assert total == 0
    assert len(groups) == 0
    assert groups == []

    expected_calls = [
        mocker.call(limit=100, offset=0, sorts="id", fields="id"),
        mocker.call(limit=test_limit, offset=test_offset, sorts="id"),
    ]
    mocked_looker_api.sdk.all_groups.assert_has_calls(expected_calls)
    assert mocked_looker_api.sdk.all_groups.call_count == len(expected_calls)


def test_get_groups_small_page(mocker, mocked_looker_api, sample_looker_group):
    """
    Test get_groups with the number of groups being lower than one page limit
    """
    test_limit = 10
    test_offset = 0
    mock_groups = [sample_looker_group] * 5

    mocked_looker_api.sdk.all_groups.side_effect = [
        mock_groups,
        [],
        mock_groups,
    ]

    groups, total = mocked_looker_api.get_groups(limit=test_limit, offset=test_offset)

    assert total == 5
    assert len(groups) == 5

    expected_calls = [
        mocker.call(limit=100, offset=0, sorts="id", fields="id"),
        mocker.call(limit=100, offset=100, sorts="id", fields="id"),
        mocker.call(limit=test_limit, offset=test_offset, sorts="id"),
    ]
    mocked_looker_api.sdk.all_groups.assert_has_calls(expected_calls)
    assert mocked_looker_api.sdk.all_groups.call_count == 3


def test_get_groups_one_page(mocker, mocked_looker_api, sample_looker_group):
    """
    Test get_groups with the number of groups being exactly one page
    """
    test_limit = 10
    test_offset = 0
    mock_groups = [sample_looker_group] * 10

    mocked_looker_api.sdk.all_groups.side_effect = [
        mock_groups,
        [],
        mock_groups,
    ]

    groups, total = mocked_looker_api.get_groups(limit=test_limit, offset=test_offset)

    assert total == 10
    assert len(groups) == 10

    expected_calls = [
        mocker.call(limit=100, offset=0, sorts="id", fields="id"),
        mocker.call(limit=100, offset=100, sorts="id", fields="id"),
        mocker.call(limit=test_limit, offset=test_offset, sorts="id"),
    ]
    mocked_looker_api.sdk.all_groups.assert_has_calls(expected_calls)
    assert mocked_looker_api.sdk.all_groups.call_count == len(expected_calls)


def test_get_groups_many_pages(mocker, mocked_looker_api, sample_looker_group):
    """
    Test get_groups with the number of groups being more than one page
    """
    test_limit = 10
    test_offset = 30
    mock_groups = [sample_looker_group] * 10
    mock_groups_page1 = [sample_looker_group] * 100
    mock_groups_page2 = [sample_looker_group] * 100
    mock_groups_page3 = [sample_looker_group] * 18

    mocked_looker_api.sdk.all_groups.side_effect = [
        mock_groups_page1,
        mock_groups_page2,
        mock_groups_page3,
        [],
        mock_groups,
    ]

    groups, total = mocked_looker_api.get_groups(limit=test_limit, offset=test_offset)

    assert total == 218
    assert len(groups) == 10

    expected_calls = [
        mocker.call(limit=100, offset=0, sorts="id", fields="id"),
        mocker.call(limit=100, offset=100, sorts="id", fields="id"),
        mocker.call(limit=100, offset=200, sorts="id", fields="id"),
        mocker.call(limit=100, offset=300, sorts="id", fields="id"),
        mocker.call(limit=test_limit, offset=test_offset, sorts="id"),
    ]
    mocked_looker_api.sdk.all_groups.assert_has_calls(expected_calls)
    assert mocked_looker_api.sdk.all_groups.call_count == len(expected_calls)


def test_search_groups_zero(mocked_looker_api, sample_groupname):
    """
    Test search_groups with the number of groups being zero
    """
    mocked_looker_api.sdk.search_groups.return_value = []
    groups, num_of_groups = mocked_looker_api.search_groups(group_name=sample_groupname)
    assert groups == []
    assert num_of_groups == 0


def test_search_groups_one(mocked_looker_api, sample_looker_group, sample_groupname, group_scim_payload):
    """
    Test search_groups with the number of groups being one
    """
    mocked_looker_api.sdk.search_groups.return_value = [sample_looker_group]
    groups, num_of_groups = mocked_looker_api.search_groups(group_name=sample_groupname)
    assert groups == [group_scim_payload]
    assert num_of_groups == 1


def test_search_groups_two(mocked_looker_api, sample_looker_group, sample_groupname):
    """
    Test search_groups with the number of groups being two. Should throw an exception
    """
    mocked_looker_api.sdk.search_groups.return_value = [
        sample_looker_group,
        sample_looker_group,
    ]

    with pytest.raises(
        AppAPIException,
        match=f"Found more than one group with name:{sample_groupname}",
    ):
        mocked_looker_api.search_groups(group_name=sample_groupname)


def test_update_group_name(mocked_looker_api, sample_looker_group, group_scim_payload):
    """
    Test update_group_name.
    """
    new_group_name = "NewName"
    sample_looker_group["name"] = new_group_name
    group_scim_payload["displayName"] = new_group_name

    mocked_looker_api.sdk.update_group.return_value = sample_looker_group
    r_group_scim = mocked_looker_api.update_group_name(group_id=987, group_name=new_group_name)

    assert r_group_scim == group_scim_payload


def test_remove_group_member(mocked_looker_api, user_scim_payload):
    """
    Test remove_group_member by removing an existing user
    """
    mocked_looker_api.sdk.delete_group_user.return_value = None
    mocked_looker_api.sdk.get_user.return_value = user_scim_payload

    mocked_looker_api.remove_group_member(group_id=987, user_id=123)


def test_remove_group_member_nonexistent(mocked_looker_api):
    """
    Test remove_group_member by removing an existing user
    """
    error_title = "Looker Not Found (404)"
    mock_404_error = looker_sdk.error.SDKError(message=f"<html><head><title>{error_title}</title></head></html>")
    mocked_looker_api.sdk.user.side_effect = mock_404_error

    mocked_looker_api.remove_group_member(group_id=987, user_id=123)


# LookerAPI update_group_membership tests - - - - - - - - - - - - - - - - - - - - - - - -
class FakeGroupManager:
    """A fake class to simulate group membership state."""

    def __init__(self, initial_members: set):
        self.members = initial_members
        self.base_group_data = {
            "id": 100,
            "displayName": "Test Group"
        }
        self.group_id = None

    def add_member(self, group_id, user_id):
        """Fake implementation that adds a user to the local set."""
        self.group_id = group_id
        self.members.add(user_id)

    def remove_member(self, group_id, user_id):
        """Fake implementation that removes a user from the local set."""
        self.group_id = group_id
        self.members.remove(user_id)

    def get_group(self, group_id):
        """
        Fake implementation that returns the group's final state,
        including the 'members' list.
        """
        self.group_id = group_id
        member_list = []
        for user_id in self.members:
            member_list.append({
                "value": user_id,
                "display": f"user_{user_id}@example.com"
            })

        final_payload = self.base_group_data.copy()
        final_payload["members"] = member_list

        return final_payload


@pytest.fixture
def mock_sdk_user_factory(mocker):
    """
    A factory to create mock Looker SDK User objects.
    They only need to have 'id' attribute.
    """
    def _factory(user_id):
        user = mocker.Mock()
        user.id = user_id
        return user
    return _factory


@pytest.fixture
def scim_members_factory():
    """
    A factory to create the 'desired_members' list
    in the SCIM format: [{"value": 1}, {"value": 2}]
    """
    def _factory(id_list):
        return [{"value": user_id} for user_id in id_list]
    return _factory


@pytest.fixture
def fake_group_manager(mocker, mocked_looker_api, mock_sdk_user_factory):
    """
    A fixture that prepares and patches the LookerAPI for state-based testing.

    It returns an instance of FakeGroupManager, allowing tests to set up
    initial state and assert against the final state.
    """

    initial_members = {1, 2}

    mocked_looker_api.sdk.all_group_users.side_effect = [
        [mock_sdk_user_factory(user_id) for user_id in initial_members],
        []
    ]

    manager = FakeGroupManager(initial_members=initial_members)

    mocker.patch.object(mocked_looker_api, "add_group_member", side_effect=manager.add_member)
    mocker.patch.object(mocked_looker_api, "remove_group_member", side_effect=manager.remove_member)
    mocker.patch.object(mocked_looker_api, "get_group", side_effect=manager.get_group)

    yield manager


def test_update_group_membership_add_and_remove(mocked_looker_api, fake_group_manager, scim_members_factory):
    """
    Tests adding and removing members using the stateful fake_group_manager.
    - Initial State: {1, 2} (from fixture)
    - Desired State: {1, 3}
    """
    group_id = 100
    desired_members = scim_members_factory([1, 3])

    result = mocked_looker_api.update_group_membership(group_id, desired_members)
    assert fake_group_manager.members == {1, 3}
    returned_member_ids = {member["value"] for member in result["members"]}
    assert returned_member_ids == {1, 3}


def test_update_group_membership_remove_all(mocked_looker_api, fake_group_manager, scim_members_factory):
    """
    Tests removing members using the stateful fake_group_manager.
    - Initial State: {1, 2} (from fixture)
    - Desired State: {}
    """
    group_id = 100
    desired_members = scim_members_factory([])

    result = mocked_looker_api.update_group_membership(group_id, desired_members)
    assert fake_group_manager.members == set()
    returned_member_ids = {member["value"] for member in result["members"]}
    assert returned_member_ids == set()


def test_update_group_membership_replace_all(mocked_looker_api, fake_group_manager, scim_members_factory):
    """
    Tests removing members using the stateful fake_group_manager.
    - Initial State: {1, 2} (from fixture)
    - Desired State: {3, 4}
    """
    group_id = 100
    desired_members = scim_members_factory([3, 4])

    result = mocked_looker_api.update_group_membership(group_id, desired_members)
    assert fake_group_manager.members == {3, 4}
    returned_member_ids = {member["value"] for member in result["members"]}
    assert returned_member_ids == {3, 4}


def test_update_group_membership_no_change(mocked_looker_api, fake_group_manager, scim_members_factory):
    """
    Tests removing members using the stateful fake_group_manager.
    - Initial State: {1, 2} (from fixture)
    - Desired State: {1, 2}
    """
    group_id = 100
    desired_members = scim_members_factory([1, 2])

    result = mocked_looker_api.update_group_membership(group_id, desired_members)
    assert fake_group_manager.members == {1, 2}
    returned_member_ids = {member["value"] for member in result["members"]}
    assert returned_member_ids == {1, 2}
