"""
Various helper functions without any specific app logic
"""

from enum import Enum

from flask import jsonify
from google.cloud import secretmanager


class ScimPayloadType(Enum):
    """Enumeration of supported SCIM resource types."""
    USER = 1
    GROUP = 2
    USER_PATCH = 3
    GROUP_PATCH = 4


def scim_error(message, status):
    """Produce a SCIM error message"""
    return jsonify(
        {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "detail": message,
            "status": status,
        }
    )


def access_secret_credential(project_id, secret_name):
    """Read secret from Google Secret Manager"""

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(name=name)
    return response.payload.data.decode("UTF-8")
