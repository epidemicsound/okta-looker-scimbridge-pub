"""
Generic classes to handle integrations of downstream apps.
"""

import abc
import os

from looker_sdk import api_settings


class AppAPIException(Exception):
    """Base exception for AppAPI errors."""


class ObjectAlreadyExists(AppAPIException):
    """Exceptions when the object is already present in the downstream app"""


class AppAPI(abc.ABC):
    """Dummy super-class specifying the required methods"""

    @abc.abstractmethod
    def create_user(self, raw_user, username):
        pass

    @abc.abstractmethod
    def delete_user(self, user_id):
        pass

    @abc.abstractmethod
    def get_user(self, user_id):
        pass

    @abc.abstractmethod
    def get_users(self, limit=None, offset=None):
        pass

    @abc.abstractmethod
    def search_users(self, email):
        pass

    @abc.abstractmethod
    def change_user_state(self, user_id, is_active):
        pass

    @abc.abstractmethod
    def update_user(self, user_id, raw_user, username):
        pass

    @abc.abstractmethod
    def add_group_member(self, group_id, user_id):
        pass

    @abc.abstractmethod
    def create_group(self, group_name):
        pass

    @abc.abstractmethod
    def delete_group(self, group_id):
        pass

    @abc.abstractmethod
    def get_group(self, group_id):
        pass

    @abc.abstractmethod
    def get_groups(self, limit, offset):
        pass

    @abc.abstractmethod
    def search_groups(self, group_name):
        pass

    @abc.abstractmethod
    def update_group_membership(self, group_id, desired_members):
        pass

    @abc.abstractmethod
    def remove_group_member(self, group_id, user_id):
        pass


class LookerDeploymentSettings(api_settings.ApiSettings):
    """Looker configuration override to enable usage of Google Secret Manager"""

    def __init__(self, *args, **kw_args):
        self.api_secret = kw_args.pop("api_secret")
        super().__init__(*args, **kw_args)

    def read_config(self) -> api_settings.SettingsConfig:
        config = super().read_config()
        config["client_secret"] = self.api_secret
        config["client_id"] = os.getenv("LOOKERSDK_CLIENT_ID")
        config["base_url"] = os.getenv("LOOKERSDK_BASE_URL")
        return config
