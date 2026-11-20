"""
Provides Looker API interface for the SCIM layer to interact with.
"""

import functools
import logging

import looker_sdk
from bs4 import BeautifulSoup

from .appapi import AppAPI, AppAPIException, ObjectAlreadyExists

LOOKER_PAGE_SIZE = 100


def handle_sdk_errors(func):
    """Decorator to catch Looker SDK errors and wrap them in AppAPIException."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except looker_sdk.error.SDKError as e:
            raise AppAPIException(f"An unexpected Looker API error occurred: {e.message}") from e
    return wrapper


class LookerAPI(AppAPI):
    """Looker API wrapper class"""

    def __init__(self, logger: logging.Logger, deployment_settings: looker_sdk.api_settings.ApiSettings = None):
        self.sdk = looker_sdk.init40(config_settings=deployment_settings)
        self.logger = logger


    # User API + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + +

    def create_user_scim_payload(self, user, email=None):
        """Generate SCIM payload with a single user object"""

        # Note: Looker does not have a good place to store externalId. It needs to be stored in app database

        return {
            "schemas": [
                "urn:ietf:params:scim:schemas:core:2.0:User",
            ],
            "id": user.id,
            "userName": email if email is not None else user.email,
            "name": {
                "givenName": user.first_name,
                "familyName": user.last_name,
            },
            "emails": [
                {
                    "primary": True,
                    "value": email if email is not None else user.email,
                    "type": "work",
                }
            ],
            "displayName": user.display_name,
            "locale": user.locale,
            "active": not user.is_disabled,
            "meta": {"resourceType": "User"},
        }


    @handle_sdk_errors
    def create_user(self, raw_user, username):
        """Create a new user object in Looker"""

        body = looker_sdk.models40.User(
            display_name=raw_user.get("displayName"),
            first_name=raw_user["name"].get("givenName"),
            last_name=raw_user["name"].get("familyName"),
            is_disabled=not raw_user.get("active"),
            locale=raw_user.get("locale"),
        )

        u, _ = self.search_users(username)
        if u:
            raise ObjectAlreadyExists(f"User with {username} username already exists in Looker")

        n_user = self.sdk.create_user(body)
        creds_email = looker_sdk.models40.CredentialsEmail(email=username)
        self.sdk.create_user_credentials_email(user_id=n_user.id, body=creds_email)

        self.logger.info(f"Created new user id:{n_user.get('id')}, email:{username}")
        return self.create_user_scim_payload(n_user, email=username)


    @handle_sdk_errors
    def delete_user(self, user_id):
        """Delete a user object in Looker"""

        self.sdk.delete_user(user_id=user_id)
        self.logger.info(f"Deleted user id:{user_id}")


    def get_user(self, user_id):
        """Retrive a user object from Looker by id"""

        try:
            g_user = self.sdk.user(user_id)

        except looker_sdk.error.SDKError as e:
            soup = BeautifulSoup(e.message, "html.parser")
            title = soup.title.string
            if title == "Looker Not Found (404)":
                return None
            raise AppAPIException(f"An unexpected Looker API error occurred: {e.message}") from e

        self.logger.debug(f"Retrieved user id:{user_id}, email:{g_user.get('email')}")
        return self.create_user_scim_payload(g_user)


    @handle_sdk_errors
    def get_users(self, limit=None, offset=None):
        """List Looker user objects with pagination and count the total number of them"""

        users = []
        total_users_count = 0
        count_offset = 0

        # Note: This is not really efficient but there is no other way how count the total number of groups
        while True:
            some_users = self.sdk.all_users(limit=LOOKER_PAGE_SIZE, offset=count_offset, sorts="id", fields="id")
            if not some_users:
                break

            total_users_count += len(some_users)
            count_offset += LOOKER_PAGE_SIZE

        looker_users = self.sdk.all_users(limit=limit, offset=offset, sorts="id")

        for g_user in looker_users:
            users.append(self.create_user_scim_payload(g_user))

        self.logger.debug(f"Retrieved {len(users)} users at offset {offset} limited to {limit} with total user count being {total_users_count}")
        return users, total_users_count


    @handle_sdk_errors
    def search_users(self, email):
        """Find user object in Looker by email (unique attribute)"""

        users = []

        # Note: We don't consider pagination here since we expect the number of returned objects to be either 1 or 0.

        looker_users = self.sdk.search_users(
            email=email,
            fields="id,email,is_disabled,first_name,last_name,locale,display_name",
            sorts="id",
        )
        if len(looker_users) > 1:
            raise AppAPIException(f"Found more than one user with email:{email}")

        for f_user in looker_users:
            users.append(self.create_user_scim_payload(f_user))

        self.logger.debug(f"Found {len(users)} users with {email} email address")
        return users, len(users)

    @handle_sdk_errors
    def change_user_state(self, user_id, is_active):
        """Update user active state"""

        body = looker_sdk.models40.User(
            is_disabled=not is_active,
        )
        u_user = self.sdk.update_user(user_id=user_id, body=body)

        self.logger.info(f"User id:{user_id} active state set to {is_active}")
        return self.create_user_scim_payload(u_user)

    @handle_sdk_errors
    def update_user(self, user_id, raw_user, username):
        """Update user object in Looker (full update)"""

        body = looker_sdk.models40.User(
            display_name=raw_user.get("displayName"),
            first_name=raw_user["name"].get("givenName"),
            last_name=raw_user["name"].get("familyName"),
            is_disabled=not raw_user.get("active"),
            locale=raw_user.get("locale"),
        )

        u_user = self.sdk.update_user(user_id=user_id, body=body)
        self.logger.info(f"Updated based user attributes of user id:{user_id}, email:{username}")

        if u_user.email != username:
            creds_email = looker_sdk.models40.CredentialsEmail(email=username)
            self.sdk.update_user_credentials_email(user_id=u_user.id, body=creds_email)
            self.logger.info(f"Updated email of user id:{user_id} from {u_user.email} to {username}")

        return self.create_user_scim_payload(u_user, email=username)


    # Group API + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + +

    def create_group_scim_payload(self, group, members=None):
        """Generate SCIM payload with a single group object"""

        # Note: We don't really need to return externalId for groups (Okta examples)
        out_members = []
        if members:
            for m in members:
                out_members.append({"value": m.id, "display": m.email})

        return {
            "schemas": [
                "urn:ietf:params:scim:schemas:core:2.0:Group",
            ],
            "id": group.id,
            "displayName": group.name,

            "members": out_members,
            "meta": {"resourceType": "Group"},
        }


    @handle_sdk_errors
    def add_group_member(self, group_id, user_id):
        if self.get_user(user_id):
            self.logger.info(f"Adding user {user_id} to group {group_id}")
            self.sdk.add_group_user(group_id, body={"user_id": user_id})
        else:
            self.logger.warning(f"user id:{user_id} not found in Looker during group membership addition")


    @handle_sdk_errors
    def create_group(self, group_name):
        """Create a new group object in Looker"""

        # Upstream can send POST even after checking whether the group exists.
        # We have chosen to handle this gracefully
        e_groups, _ = self.search_groups(group_name)
        if e_groups:
            self.logger.info(f"Group creation aborted since the group {group_name} already exists")
            return e_groups[0]

        body = looker_sdk.models40.Group(name=group_name)
        n_group = self.sdk.create_group(body)

        self.logger.info(f"Created new group id:{n_group.get('id')}, name:{group_name}")
        return self.create_group_scim_payload(n_group)


    @handle_sdk_errors
    def delete_group(self, group_id):
        """Delete a group object in Looker"""

        self.sdk.delete_group(group_id)
        self.logger.info(f"Deleted group id:{group_id}")


    def get_group(self, group_id):
        """Retrive a group object from Looker by id"""

        try:
            g_group = self.sdk.group(group_id)
            g_members = []
            count_offset = 0
            while True:
                members_page = self.sdk.all_group_users(group_id, limit=LOOKER_PAGE_SIZE, offset=count_offset, sorts="id")
                if not members_page:
                    break

                count_offset += LOOKER_PAGE_SIZE
                g_members.extend(members_page)

        except looker_sdk.error.SDKError as e:
            soup = BeautifulSoup(e.message, "html.parser")
            title = soup.title.string
            if title == "Looker Not Found (404)":
                return None
            raise AppAPIException(f"An unexpected Looker API error occurred: {e.message}") from e

        self.logger.debug(f"Retrieved group id:{group_id} name:{g_group.get('name')}")
        return self.create_group_scim_payload(g_group, g_members)


    @handle_sdk_errors
    def get_groups(self, limit, offset):
        """List Looker group objects with pagination and count the total number of them"""

        groups = []
        total_group_count = 0
        count_offset = 0

        # Note: This is not really efficient but there is no other way how count the total number of groups
        while True:
            some_groups = self.sdk.all_groups(limit=LOOKER_PAGE_SIZE, offset=count_offset, sorts="id", fields="id")
            if not some_groups:
                break

            total_group_count += len(some_groups)
            count_offset += LOOKER_PAGE_SIZE

        g_groups = self.sdk.all_groups(limit=limit, offset=offset, sorts="id")
        for group in g_groups:
            groups.append(self.create_group_scim_payload(group))

        self.logger.debug(f"Retrieved {len(g_groups)} groups at offset {offset} limited to {limit} with total user count being {total_group_count}")
        return groups, total_group_count


    @handle_sdk_errors
    def search_groups(self, group_name):
        """Find group object in Looker by name (unique attribute)"""

        groups = []

        s_groups = self.sdk.search_groups(
            name=group_name,
            sorts="id",
        )
        if len(s_groups) > 1:
            raise AppAPIException(f"Found more than one group with name:{group_name}")

        for group in s_groups:
            groups.append(self.create_group_scim_payload(group))

        self.logger.debug(f"Found {len(s_groups)} groups with {group_name} name")
        return groups, len(groups)


    @handle_sdk_errors
    def update_group_name(self, group_id, group_name):
        """Update name of a group in Looker"""

        body = looker_sdk.models40.Group(name=group_name)
        lgroup = self.sdk.update_group(group_id, body)

        self.logger.info(f"Updated name of the group id:{group_id} to {group_name}")
        return self.create_group_scim_payload(lgroup)


    @handle_sdk_errors
    def update_group_membership(self, group_id, desired_members):
        """Update members of a Looker group"""

        current_members = []
        count_offset = 0
        while True:
            members_page = self.sdk.all_group_users(group_id, limit=LOOKER_PAGE_SIZE, offset=count_offset, sorts="id")
            if not members_page:
                break

            count_offset += LOOKER_PAGE_SIZE
            current_members.extend(members_page)

        current_member_ids = {member.id for member in current_members}
        desired_member_ids = {member["value"] for member in desired_members}

        members_to_add = desired_member_ids - current_member_ids
        for user_id in members_to_add:
            self.add_group_member(group_id, user_id)

        members_to_remove = current_member_ids - desired_member_ids
        for user_id in members_to_remove:
            self.remove_group_member(group_id, user_id)

        self.logger.info(f"Updated memberships for group {group_id}")
        return self.get_group(group_id)


    @handle_sdk_errors
    def remove_group_member(self, group_id, user_id):
        if self.get_user(user_id):
            self.logger.info(f"Removing user {user_id} from group {group_id}")
            self.sdk.delete_group_user(group_id, user_id)
        else:
            self.logger.warning(f"user id:{user_id} not found in Looker during group membership removal")
