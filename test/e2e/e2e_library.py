"""
Function library intended for e2e_app.py
"""

import asyncio
import os
import sys
from enum import Enum, auto

import looker_sdk
from okta.client import Client as OktaClient
from okta.exceptions.exceptions import OktaAPIException
from okta.models.add_group_request import AddGroupRequest
from okta.models.app_user_assign_request import AppUserAssignRequest
from okta.models.app_user_credentials_request_payload import \
    AppUserCredentialsRequestPayload
from okta.models.app_user_profile_request_payload import \
    AppUserProfileRequestPayload
from okta.models.app_user_update_request import AppUserUpdateRequest
from okta.models.okta_user_group_profile import OktaUserGroupProfile
from okta.models.update_user_request import UpdateUserRequest
from okta.models.create_group_push_mapping_request import CreateGroupPushMappingRequest
from okta.models.update_group_push_mapping_request import UpdateGroupPushMappingRequest
from okta.models.group_push_mapping_status_upsert import GroupPushMappingStatusUpsert

DEBUG_OUTPUT = os.getenv("TEST_DEBUG")
DEFAULT_TIMEOUT = 120


class UserState(Enum):
    """Enum listing possible Looker user states"""
    NOT_PRESENT = auto()
    PRESENT_ACTIVE = auto()
    PRESENT_INACTIVE = auto()


class GroupState(Enum):
    """Enum listing possible Looker group states"""
    NOT_PRESENT = auto()
    PRESENT = auto()


def print_debug(message):
    if DEBUG_OUTPUT:
        print(message)


def fail_exit(message):
    print(f"::error:: {message}", file=sys.stderr)
    sys.exit(1)


async def poll_for_state(check_function, *args, timeout=DEFAULT_TIMEOUT, **kwargs):
    """
    Generic poller that retries an async check function until it returns a falsy value (None, empty string).
    """
    sleep_duration = 0
    total_sleep = 0
    while total_sleep < timeout:
        message = await check_function(*args, **kwargs)
        if not message:
            return  # Success
        sleep_duration = min(10, 1 + sleep_duration)
        print_debug(f"Polling state for {check_function.__name__} with timeout in {sleep_duration}s")
        await asyncio.sleep(sleep_duration)
        total_sleep += sleep_duration

    fail_exit(message)  # Exit with the last received message on timeout


# Users - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


# Looker user methods
async def find_looker_user(looker, email):
    existing_users = looker.search_users(
        email=email,
        fields="id,email,is_disabled,first_name,last_name,locale,display_name",
    )

    return existing_users[0] if existing_users else None


async def ensure_looker_user_removed(looker, email):

    user = await find_looker_user(looker, email)
    if user:
        print_debug(f"Removing user {email}")
        looker.delete_user(user_id=user.id)


async def ensure_looker_user_exists(looker, user, is_disabled):
    body = looker_sdk.models40.User(
        display_name=(user["givenName"] + " " + user["familyName"]),
        first_name=user["givenName"],
        last_name=user["familyName"],
        is_disabled=False,
        locale=user.get("locale").replace("_", "-"),
    )

    looker_user = await find_looker_user(looker, user["login"])

    if not looker_user:
        print_debug(f"Creating user {user['login']}")
        looker_user = looker.create_user(body)
        creds_email = looker_sdk.models40.CredentialsEmail(email=user["login"])
        looker.create_user_credentials_email(user_id=looker_user.id, body=creds_email)

    print_debug(f"Updating user {user['login']}")
    body.is_disabled = is_disabled
    looker.update_user(user_id=looker_user.id, body=body)


async def check_looker_user_logic(looker, user, expected_state: UserState, only_state=False):
    looker_user = await find_looker_user(looker, email=user["login"])

    if expected_state == UserState.NOT_PRESENT:
        if looker_user:
            return f"User {user['login']} present when it should not be"

        return

    if not looker_user:
        return f"User {user['login']} is missing"

    is_active = not looker_user.is_disabled

    if expected_state == UserState.PRESENT_ACTIVE and not is_active:
        return f"User {user['login']} is present but not active. It should be active"

    if expected_state == UserState.PRESENT_INACTIVE and is_active:
        return f"User {user['login']} is present but active. It should be inactive"

    if not only_state:
        expected_display_name = f"{user['givenName']} {user['familyName']}"
        checks = {
            "first_name": (looker_user.first_name, user["givenName"]),
            "last_name": (looker_user.last_name, user["familyName"]),
            "display_name": (looker_user.display_name, expected_display_name),
            "locale": (looker_user.locale.replace("-", "_"), user["locale"]),
        }

        for attr, (actual, expected) in checks.items():
            if actual != expected:
                return f"User {user['login']} has incorrect {attr}. Got '{actual}', expected '{expected}'."


async def check_looker_user(looker, user, expected_state: UserState, timeout=DEFAULT_TIMEOUT, only_state=False):
    print_debug(f"Checking if user {user['login']} is {expected_state}")
    await poll_for_state(
        check_looker_user_logic,
        timeout=timeout,
        looker=looker,
        user=user,
        expected_state=expected_state,
        only_state=only_state,
    )


# Okta user methods
async def update_okta_user(okta: OktaClient, user):
    print_debug(f"Updating user profile {user['login']}")

    updated_user = UpdateUserRequest.from_dict({
        "profile": {
            "login": user['login'],
            "email": user['login'],
            "firstName": user["givenName"],
            "lastName": user["familyName"],
            "locale": user["locale"],
        }
    })

    _, _, _ = await okta.replace_user(user["id"], updated_user)


async def assign_user_to_app(okta: OktaClient, app_id, user):
    print_debug(f"Assigning user {user['login']} to {app_id}")

    app_user = AppUserAssignRequest.from_dict({"id": user["id"]})
    _, _, _ = await okta.assign_user_to_application(app_id, app_user)


async def unassign_user_from_app(okta: OktaClient, app_id, user_id):
    print_debug(f"Unassigning user {user_id} from {app_id}")
    await okta.unassign_user_from_application(app_id, user_id)


async def update_user_assignment(okta: OktaClient, app_id, user):
    display_name = f"{user['givenName']} {user['familyName']}"

    app_credentials = AppUserCredentialsRequestPayload.from_dict({
        "user_name": user['login'],
    })
    app_user_credentials = AppUserUpdateRequest(app_credentials)

    app_profile = AppUserProfileRequestPayload.from_dict({
        "profile": {
            "displayName": display_name,
            "locale": user['locale'],
            "emailType": "work",
            "familyName": user['familyName'],
            "email": user['login'],
            "givenName": user['givenName'],
        },
    })
    app_user_profile = AppUserUpdateRequest(app_profile)

    await okta.update_application_user(app_id, user["id"], app_user_credentials)
    await okta.update_application_user(app_id, user["id"], app_user_profile)


async def check_okta_assignment(okta: OktaClient, app_id, user, should_be_assigned=True):
    print_debug(f"Checking if user {user['login']} is assigned to {app_id}. Should? {should_be_assigned}")

    try:
        app_user, _, _ = await okta.get_application_user(app_id, user["id"])
    except OktaAPIException as e:
        if e.args[0]["errorCode"] != "E0000007":
            raise
        app_user = None

    if not app_user and should_be_assigned:
        fail_exit(f"user {user['login']} is not asssigned but it should be")

    if app_user:
        if not should_be_assigned:
            fail_exit(f"user {user['login']} is asssigned but it should not be")

        timeout = 0
        while app_user.sync_state in {"SYNCING", "OUT_OF_SYNC"}:
            if timeout > 120:
                fail_exit(f"Timed out while waiting for {user['login']} to sync")
            print_debug(f"Change for user {user['login']} is still being pushed ")
            await asyncio.sleep(1)
            app_user, _, _ = await okta.get_application_user(app_id, user["id"])
            timeout += 1

        if app_user.sync_state != "SYNCHRONIZED":
            fail_exit(f"user {user['login']} is asssigned but is in unexpected sync state: {app_user.sync_state}")

# Groups - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


# Looker group methods
async def find_looker_group(looker, group_name):
    s_groups = looker.search_groups(name=group_name)
    return s_groups[0] if s_groups else None


async def ensure_looker_group_removed(looker, group_name):

    group = await find_looker_group(looker, group_name)
    if group:
        print_debug(f"Removing group {group_name}")
        looker.delete_group(group.id)


async def ensure_looker_group_exists(looker, group_name):

    group = await find_looker_group(looker, group_name)

    if not group:
        print_debug(f"Creating group {group_name}")
        body = looker_sdk.models40.Group(name=group_name)
        looker.create_group(body)


async def check_looker_group_logic(looker, group_name, expected_state: GroupState):

    group = await find_looker_group(looker, group_name)

    if not group and expected_state == expected_state.PRESENT:
        return f"Group {group_name} is missing even though it should be present"

    if group and expected_state == expected_state.NOT_PRESENT:
        return f"Group {group_name} is present even though it should't be there"


async def check_looker_group(looker, group_name, expected_state: GroupState, timeout=DEFAULT_TIMEOUT):
    print_debug(f"Checking if group {group_name} is {expected_state}")

    await poll_for_state(
        check_looker_group_logic,
        timeout=timeout,
        looker=looker,
        group_name=group_name,
        expected_state=expected_state
    )


async def check_looker_group_membership_logic(looker, group_name, expected_members):

    group = await find_looker_group(looker, group_name)

    if not group:
        return f"Group {group_name} not found"

    group_members = looker.search_users(group_id=group.id)
    group_members_emails = {member.email for member in group_members}

    unexpected_members = group_members_emails - expected_members
    missing_members = expected_members - group_members_emails

    if unexpected_members or missing_members:
        error_message = [f"Unexpected membership state in group: {group_name}."]
        if unexpected_members:
            error_message.append(f" Found unexpected members: {unexpected_members}.")
        if missing_members:
            error_message.append(f" Mmissing members: {missing_members}.")

        return " ".join(error_message)


async def check_looker_group_membership(looker, group_name, expected_members, timeout=DEFAULT_TIMEOUT):
    print_debug(f"Checking memberships in group {group_name}")

    await poll_for_state(
        check_looker_group_membership_logic,
        timeout=timeout,
        looker=looker,
        group_name=group_name,
        expected_members=expected_members
    )


# Okta group methods
async def add_okta_user_to_group(okta, group_id, user_id):
    print_debug(f"Adding user {user_id} to group {group_id}")
    await okta.assign_user_to_group(group_id, user_id)


async def remove_okta_user_from_group(okta, group_id, user_id):
    print_debug(f"Removing user {user_id} from group {group_id}")
    await okta.unassign_user_from_group(group_id, user_id)


async def update_okta_group(okta: OktaClient, group):
    updated_group = AddGroupRequest.from_dict({})
    updated_group.profile = OktaUserGroupProfile.from_dict({
        'name': group["name"]
    })

    await okta.replace_group(group["id"], updated_group)


async def ensure_okta_group_memberships(okta: OktaClient, group_id, users):
    current_members, _, _ = await okta.list_group_users(group_id)
    current_member_ids = {member.id for member in current_members}
    desired_member_ids = {member["id"] for member in users}

    members_to_add = desired_member_ids - current_member_ids
    for user_id in members_to_add:
        await add_okta_user_to_group(okta, group_id, user_id)

    members_to_remove = current_member_ids - desired_member_ids
    for user_id in members_to_remove:
        await remove_okta_user_from_group(okta, group_id, user_id)


async def find_push_group_mapping(okta: OktaClient, app_id, group_id):

    mappings, _, _ = await okta.list_group_push_mappings(app_id)

    if mappings:
        for push_group in mappings:
            if push_group.source_group_id == group_id:
                return push_group

    return None


async def check_push_group_mapping(okta: OktaClient, app_id, group_id, should_be_mapped=True):
    print_debug(f"Checking push group mapping app:{app_id} group:{group_id} should_be_present:{should_be_mapped}")

    pg_mapping = await find_push_group_mapping(okta, app_id, group_id)

    if not should_be_mapped and pg_mapping:
        fail_exit(f"Group {group_id} is mapped as push group but it shouldn't be")

    if should_be_mapped and not pg_mapping:
        fail_exit(f"Group {group_id} should be mapped as push group but it is not there")

    if pg_mapping and pg_mapping.status == "ERROR":
        fail_exit(f"Group {group_id} is mapped but the mapping is in ERROR state")


async def create_push_group_mapping(okta: OktaClient, app_id, group):
    print_debug(f"Creating push group mapping group:{group['name']}, app:{app_id}")

    body = CreateGroupPushMappingRequest.from_dict({
      "sourceGroupId": group["id"],
      "targetGroupName": group["name"],
    })

    await okta.create_group_push_mapping(app_id, body)


async def remove_push_group_mapping(okta: OktaClient, app_id, group_id):

    pg_mapping = await find_push_group_mapping(okta, app_id, group_id)
    if not pg_mapping:
        print_debug(f"No push group mapping found for app:{app_id} group:{group_id}")
        return

    body = UpdateGroupPushMappingRequest.from_dict({
      "status": GroupPushMappingStatusUpsert.INACTIVE,
    })

    await okta.update_group_push_mapping(app_id, pg_mapping.id, body)

    await okta.delete_group_push_mapping(app_id, pg_mapping.id, delete_target_group=True)
