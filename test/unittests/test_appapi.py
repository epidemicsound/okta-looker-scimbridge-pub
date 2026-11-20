"""
Set of unit tests for appappi/appapi.py
"""

import pytest
from looker_sdk import api_settings

from app.appapi.appapi import LookerDeploymentSettings


def test_init_fails_without_api_secret():
    """
    Tests that the class __init__ raises a KeyError
    if the 'api_secret' keyword argument is missing.
    """
    with pytest.raises(KeyError, match="api_secret"):
        LookerDeploymentSettings()


def test_read_config_overrides_and_adds_settings(mocker, monkeypatch):
    """
    Tests that read_config correctly:
    1. Calls the parent's read_config().
    2. Overwrites 'client_secret' with the 'api_secret'.
    3. Adds 'client_id' and 'base_url' from environment variables.
    """

    monkeypatch.setenv("LOOKERSDK_CLIENT_ID", "test-client-id-from-env")
    monkeypatch.setenv("LOOKERSDK_BASE_URL", "https://test.looker.com")

    mock_base_config = {
        "parent_key": "parent_value",
        "client_secret": "old-secret-to-be-overwritten"
    }
    mocker.patch.object(
        api_settings.ApiSettings,
        "read_config",
        return_value=mock_base_config
    )

    test_secret = "my-secret-from-google"
    settings = LookerDeploymentSettings(api_secret=test_secret)

    final_config = settings.read_config()

    assert settings.api_secret == test_secret

    expected_config = {
        "parent_key": "parent_value",
        "client_secret": "my-secret-from-google",
        "client_id": "test-client-id-from-env",
        "base_url": "https://test.looker.com"
    }

    assert final_config == expected_config
