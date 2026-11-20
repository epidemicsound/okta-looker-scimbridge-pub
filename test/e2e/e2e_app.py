#!/usr/bin/env python
"""
e2e test suite which runs against Okta and Looker environments
"""

import asyncio
import copy
import os

import looker_sdk
from e2e_library import (GroupState, UserState, add_okta_user_to_group,
                         assign_user_to_app, check_looker_group,
                         check_looker_group_membership, check_looker_user,
                         check_okta_assignment, check_push_group_mapping,
                         create_push_group_mapping, ensure_looker_group_exists,
                         ensure_looker_group_removed,
                         ensure_looker_user_exists, ensure_looker_user_removed,
                         ensure_okta_group_memberships,
                         remove_okta_user_from_group,
                         remove_push_group_mapping, unassign_user_from_app,
                         update_okta_group, update_okta_user,
                         update_user_assignment)
from okta.client import Client as OktaClient
from okta.exceptions.exceptions import OktaAPIException

DEBUG_OUTPUT = os.getenv("TEST_DEBUG")

required_vars = ["SCIM_BRIDGE_AIW_APPID", "SCIM_BRIDGE_OIN_APPID"]
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    raise ValueError(
        f"CRITICAL: The following required environment variables are missing or empty: "
        f"{', '.join(missing_vars)}"
    )

SCIM_BRIDGE_AIW_APPID = os.getenv("SCIM_BRIDGE_AIW_APPID")
SCIM_BRIDGE_OIN_APPID = os.getenv("SCIM_BRIDGE_OIN_APPID")

TEST_USER1 = {"id": "<MISSING-OKTA-USER-ID>", "login": "<MISSING-OKTA-USERNAME>", "givenName": "Looker 1", "familyName": "Test Account", "locale": "en_US"}
TEST_USER2 = {"id": "<MISSING-OKTA-USER-ID>", "login": "<MISSING-OKTA-USERNAME>", "givenName": "Looker 2", "familyName": "Test Account", "locale": "sv_SE"}
TEST_USER3 = {"id": "<MISSING-OKTA-USER-ID>", "login": "<MISSING-OKTA-USERNAME>", "givenName": "Looker 3", "familyName": "Test Account", "locale": "en_US"}
TEST_USERS = [TEST_USER1, TEST_USER2, TEST_USER3]
TEST_GROUP1 = {"id": "<MISSING-OKTA-GROUP-ID>", "name": "Looker Push Test 1"}
TEST_GROUP2 = {"id": "<MISSING-OKTA-GROUP-ID>", "name": "Looker Push Test 2"}
TEST_GROUP3 = {"id": "<MISSING-OKTA-GROUP-ID>", "name": "Looker Push Test 3"}
TEST_GROUPS = [TEST_GROUP1, TEST_GROUP2, TEST_GROUP3]


async def okta_cleanup(okta, test_app_id, phase):

    print(f"{phase} Removing Okta push group mappings")
    for group in TEST_GROUPS:
        await remove_push_group_mapping(okta, test_app_id, group["id"])

    print(f"{phase} Removing Okta app user assigments")
    for user in TEST_USERS:
        try:
            await unassign_user_from_app(okta, test_app_id, user["id"])
        except OktaAPIException:
            pass

    print(f"{phase} Reset Okta users to default state")
    for user in TEST_USERS:
        await update_okta_user(okta, user)

    print(f"{phase} Reset Okta groups to default state")
    for group in TEST_GROUPS:
        await update_okta_group(okta, group)


async def test_app(okta, looker, test_app_id):
    # pylint: disable=too-many-statements

    phase = "[(0) INIT]"
    print(f"{phase} Testing app {test_app_id}")

    print(f"{phase} Making sure we start with a clean slate")
    await okta_cleanup(okta, test_app_id, phase)

    print(f"{phase} Prepare members in Okta groups")
    await ensure_okta_group_memberships(okta, TEST_GROUPS[0]["id"], [TEST_USERS[0], TEST_USERS[1]])
    await ensure_okta_group_memberships(okta, TEST_GROUPS[1]["id"], [])
    await ensure_okta_group_memberships(okta, TEST_GROUPS[2]["id"], [TEST_USERS[2]])

    print(f"{phase} Setting up users and groups in Looker")
    await ensure_looker_user_removed(looker, email="<MISSING-EMAIL-ADDRESS>")
    await ensure_looker_user_removed(looker, email=TEST_USERS[0]["login"])
    await ensure_looker_user_exists(looker, user=TEST_USERS[1], is_disabled=False)
    await ensure_looker_user_exists(looker, user=TEST_USERS[2], is_disabled=True)

    await ensure_looker_group_removed(looker, "Looker Push Test 1 Renamed")
    await ensure_looker_group_removed(looker, "Looker Push Test 2 Renamed")
    await ensure_looker_group_removed(looker, TEST_GROUPS[0]["name"])
    await ensure_looker_group_exists(looker, TEST_GROUPS[1]["name"])
    await ensure_looker_group_exists(looker, TEST_GROUPS[2]["name"])

    # Okta workaround. It seems Okta sometimes does not handle well group member remove and add events in quick succession
    # We will give it more time to process the removals so the following additions are more likely to go through.
    await asyncio.sleep(5)

    print(f"{phase} Double checking state of users and groups in Looker")
    await check_looker_user(looker, TEST_USERS[0], UserState.NOT_PRESENT)
    await check_looker_user(looker, TEST_USERS[1], UserState.PRESENT_ACTIVE)
    await check_looker_user(looker, TEST_USERS[2], UserState.PRESENT_INACTIVE)

    await check_looker_group(looker, TEST_GROUPS[0]["name"], GroupState.NOT_PRESENT)
    await check_looker_group(looker, TEST_GROUPS[1]["name"], GroupState.PRESENT)
    await check_looker_group(looker, TEST_GROUPS[2]["name"], GroupState.PRESENT)

    phase = "[(1) Provisioning]"
    print(f"{phase} Assigning users to Okta app")
    for user in TEST_USERS:
        await assign_user_to_app(okta, test_app_id, user)

    print(f"{phase} Mapping push groups")
    for group in TEST_GROUPS:
        await create_push_group_mapping(okta, test_app_id, group)

    print(f"{phase} Updating group memberships")
    await add_okta_user_to_group(okta, TEST_GROUPS[0]["id"], TEST_USERS[2]["id"])
    await remove_okta_user_from_group(okta, TEST_GROUPS[0]["id"], TEST_USERS[0]["id"])

    for user in TEST_USERS:
        await add_okta_user_to_group(okta, TEST_GROUPS[1]["id"], user["id"])

    await remove_okta_user_from_group(okta, TEST_GROUPS[2]["id"], TEST_USERS[2]["id"])

    print(f"{phase} Checking state of Okta assigments")
    for user in TEST_USERS:
        await check_okta_assignment(okta, test_app_id, user)

    print(f"{phase} Checking state of Okta group mappings")
    for group in TEST_GROUPS:
        await check_push_group_mapping(okta, test_app_id, group["id"])

    print(f"{phase} Checking state of users and groups in Looker")
    for user in TEST_USERS:
        await check_looker_user(looker, user, UserState.PRESENT_ACTIVE)

    for group in TEST_GROUPS:
        await check_looker_group(looker, group["name"], GroupState.PRESENT)

    # Check Looker group membership
    print(f"{phase} Checking Looker grop membership")
    await check_looker_group_membership(looker, TEST_GROUPS[0]["name"], {TEST_USERS[1]["login"], TEST_USERS[2]["login"]})
    await check_looker_group_membership(looker, TEST_GROUPS[1]["name"], {TEST_USERS[0]["login"], TEST_USERS[1]["login"], TEST_USERS[2]["login"]})
    await check_looker_group_membership(looker, TEST_GROUPS[2]["name"], set())

    phase = "[(2) Update values]"
    print(f"{phase} Changing user attribute values")

    # User update first name test
    user0_mod = copy.deepcopy(TEST_USERS[0])
    user0_mod["givenName"] = "Elmo"
    await update_user_assignment(okta, test_app_id, user0_mod)

    # User update change username test
    user1_mod = copy.deepcopy(TEST_USERS[1])
    user1_mod["login"] = "<MISSING-EMAIL-ADDRESS>"
    user1_mod["familyName"] = "Blaster"
    # It is important to change user profile.
    # Changing username in application user assignment profile results in Okta deprovisioning
    # the original user in the downstream app and creating a new one.
    await update_okta_user(okta, user1_mod)

    # User update change locale test
    user2_mod = copy.deepcopy(TEST_USERS[2])
    user2_mod["locale"] = "de_DE"
    await update_user_assignment(okta, test_app_id, user2_mod)

    # Group rename test
    group0_mod = copy.deepcopy(TEST_GROUPS[0])
    group0_mod["name"] = "Looker Push Test 1 Renamed"
    await update_okta_group(okta, group0_mod)

    # Group rename forth and back test
    group1_mod = copy.deepcopy(TEST_GROUPS[1])
    group1_mod["name"] = "Looker Push Test 2 Renamed"
    await update_okta_group(okta, group0_mod)
    await update_okta_group(okta, TEST_GROUPS[1])

    print(f"{phase} Checking changed attribute values in Looker")
    await check_looker_user(looker, user0_mod, UserState.PRESENT_ACTIVE)
    await check_looker_user(looker, user1_mod, UserState.PRESENT_ACTIVE)
    await check_looker_user(looker, user2_mod, UserState.PRESENT_ACTIVE)

    await check_looker_group(looker, group0_mod["name"], GroupState.PRESENT)
    await check_looker_group(looker, TEST_GROUPS[1]["name"], GroupState.PRESENT)

    phase = "[(X) Cleanup]"
    print(f"{phase} Starting cleaup")
    await okta_cleanup(okta, test_app_id, phase)

    print(f"{phase} Checking user and group removals in Looker")
    await check_looker_user(looker, TEST_USERS[0], UserState.PRESENT_INACTIVE, only_state=True)
    await check_looker_user(looker, user1_mod, UserState.PRESENT_INACTIVE, only_state=True)
    await check_looker_user(looker, TEST_USERS[2], UserState.PRESENT_INACTIVE, only_state=True)

    for group in TEST_GROUPS:
        await check_looker_group(looker, group["name"], GroupState.NOT_PRESENT)
    await check_looker_group(looker, group0_mod["name"], GroupState.NOT_PRESENT)
    await check_looker_group(looker, group1_mod["name"], GroupState.NOT_PRESENT)

    print(f"{phase} Removing users from Looker")
    await ensure_looker_user_removed(looker, email="<MISSING-EMAIL-ADDRESS>")


async def main():
    config = {'raiseException': True}
    okta = OktaClient(config)
    looker = looker_sdk.init40()

    await test_app(okta, looker, SCIM_BRIDGE_AIW_APPID)
    await test_app(okta, looker, SCIM_BRIDGE_OIN_APPID)

asyncio.run(main())
