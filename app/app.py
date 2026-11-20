"""
Flask SCIM API interface tailored for Okta SCIM operations.
Currently it works only with Looker and there are several GCP dependencies.
However the intent is to make this modular so the downstream API wrappers
can be swapped and infrastructure services (e.g. Google Secret Manager)
are easy to replace with something else.
"""

import logging
import os
import re
import secrets
import sys
from functools import wraps

import google.cloud.logging

# Workaround to make pytest work with this file
try:
    from appapi.appapi import (AppAPIException, LookerDeploymentSettings,
                               ObjectAlreadyExists)
    from appapi.looker import LookerAPI
    from database import DictDatabase, GoogleFirestore
    from helpers import ScimPayloadType, access_secret_credential, scim_error
except ModuleNotFoundError:
    from app.appapi.appapi import (AppAPIException, LookerDeploymentSettings, ObjectAlreadyExists)
    from app.appapi.looker import LookerAPI
    from app.database import GoogleFirestore, DictDatabase
    from app.helpers import access_secret_credential, scim_error, ScimPayloadType

from flask import Flask, abort, jsonify, make_response, request
from google.api_core import exceptions as api_exceptions
from google.auth import exceptions as auth_exceptions
from pydantic import ValidationError
from scim2_models import Group, PatchOp, User
from werkzeug.exceptions import BadRequest

# INIT - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

# Initialize Flask app
app = Flask(__name__)

if not os.environ.get("APP_ENV") == "test":

    # Initialize database based on the environment. K_SERVICE indicates Cloud Run environment.
    if os.getenv("K_SERVICE"):
        GCP_LOG_LEVEL = logging.DEBUG if os.getenv("APP_DEBUG") else logging.INFO
        gcp_log_client = google.cloud.logging.Client()
        gcp_log_client.setup_logging(log_level=GCP_LOG_LEVEL)

        app.db = GoogleFirestore(os.getenv("DATABASE_NAME", "okta-looker-scim-bridge"))
        app.logger.info("App is now running in Cloud Run")
    else:
        app.db = DictDatabase()
        if __name__ != '__main__':
            gunicorn_logger = logging.getLogger('gunicorn.error')
            app.logger.handlers = gunicorn_logger.handlers
            app.logger.setLevel(logging.DEBUG)
            app.logger.info("App is now being served locally by gunicorn")

    # Load configuration
    config_type = os.getenv("CONFIGURATION_TYPE", "local")

    if config_type == "gcp":
        # SCIM API key and Looker Client Secret are expected to be in Google Secret Manager
        # Rest of the Looker configuration is to be loaded exclusively from env variable
        gcp_project_id = os.getenv("GCP_PROJECT_ID")

        try:
            app.config["API_KEY"] = access_secret_credential(gcp_project_id, "scim_api_key")
            looker_api_client_secret = access_secret_credential(gcp_project_id, "looker_secret")

        except auth_exceptions.DefaultCredentialsError as e:
            app.logger.critical("Unable to Authenticate to Google Cloud. Reason: %s", e)
            sys.exit(1)

        except api_exceptions.GoogleAPICallError as e:
            app.logger.critical("Unable to load necessary secrets from Google Secret Manager. Reason: %s", e)
            sys.exit(1)

        app.appapi = LookerAPI(app.logger, deployment_settings=LookerDeploymentSettings(api_secret=looker_api_client_secret))

    elif config_type in ("environ", "local"):
        app.config["API_KEY"] = os.getenv("SCIM_API_KEY")
        if not app.config["API_KEY"]:
            app.logger.critical("SCIM_API_KEY is not set")
            sys.exit(1)

        if config_type == "environ":
            # Looker configuration is expected to be loaded exclusively from env variables
            looker_api_client_secret = os.getenv("LOOKERSDK_CLIENT_SECRET")
            if not looker_api_client_secret:
                app.logger.critical("LOOKERSDK_CLIENT_SECRET is not set")
                sys.exit(1)

            app.appapi = LookerAPI(app.logger, deployment_settings=LookerDeploymentSettings(api_secret=looker_api_client_secret))
        else:
            # Looker configuration is expected to be loaded by the default method
            app.appapi = LookerAPI(app.logger, deployment_settings=None)

    else:
        app.logger.critical("Unknown CONFIGURATION_TYPE: %s", config_type)
        sys.exit(1)


# HELPERS - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

def validate_json(payload_type):
    """
    A decorator that validates incoming JSON against a Pydantic model.

    If validation succeeds, it injects the validated data as a
    'scim_data' keyword argument into the wrapped function.

    If validation fails, it returns a 400 Bad Request response.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                payload = request.get_json(silent=False)
                if not payload:
                    raise BadRequest("Request body must contain non-empty JSON.")

                if payload_type == ScimPayloadType.USER:
                    User.model_validate(payload)
                elif payload_type == ScimPayloadType.GROUP:
                    Group.model_validate(payload)
                elif payload_type == ScimPayloadType.USER_PATCH:
                    PatchOp[User].model_validate(payload)
                elif payload_type == ScimPayloadType.GROUP_PATCH:
                    PatchOp[Group].model_validate(payload)

            except BadRequest as e:
                app.logger.error("Request body was not valid JSON. Reason: %s", e)
                return make_response(scim_error("Invalid JSON", "400"), 400)

            except ValidationError as e:
                error_message = f"Validation error: {e}"
                app.logger.error(error_message, exc_info=True)
                return make_response(scim_error("Invalid SCIM payload", "400"), 400)

            return func(*args, **kwargs)
        return wrapper
    return decorator


def auth_required(func):
    """Flask decorator to require the presence of a valid Authorization header."""

    @wraps(func)
    def check_auth(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        m = re.match(r"^Bearer\s+(.+)$", auth_header)

        if m and secrets.compare_digest(m.group(1), app.config["API_KEY"]):
            return func(*args, **kwargs)

        return make_response(scim_error("Authentication failed", "401"), 401)

    return check_auth


# ROUTES - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

@app.route("/scim/v2/Users", methods=["GET"])
@auth_required
def get_users():
    """Get SCIM Users"""

    start_index = request.args.get("startIndex", 1, type=int)
    offset = start_index - 1
    limit = request.args.get("count", 100, type=int)

    if "filter" in request.args:
        # This assumes Okta always uses filter to search for a single user as documented in https://developer.okta.com/docs/reference/scim/scim-20/
        m = re.match(r'userName eq "(.*)"', request.args["filter"])
        if m:
            username = m.group(1)
        else:
            message = "Unexpected filter: " + request.args["filter"]
            return make_response(scim_error(message, 501), 501)

        try:
            users, total_user_count = app.appapi.search_users(username)
        except AppAPIException as e:
            error_message = f"Unexpected error when searching for user {username}"
            app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
            return make_response(scim_error(error_message, 500), 500)
    else:
        try:
            users, total_user_count = app.appapi.get_users(limit, offset)
        except AppAPIException as e:
            error_message = f"Unexpected error when geting all users at offset:{offset} with limit:{limit}"
            app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
            return make_response(scim_error(error_message, 500), 500)

    for user in users:
        db_user = app.db.find_user_by_id(user["id"])
        if db_user:
            user["externalId"] = db_user.get("idp_id")
        else:
            app.logger.info("Okta user ID not found in the database for user with Looker ID %s", user["id"])

    response = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total_user_count,
        "startIndex": start_index,
        "itemsPerPage": len(users),
        "Resources": users,
    }
    app.logger.debug(response)
    return make_response(jsonify(response), 200)


@app.route("/scim/v2/Users/<string:user_id>", methods=["GET"])
@auth_required
def get_user(user_id):
    """Get SCIM User"""

    try:
        user = app.appapi.get_user(user_id)

    except AppAPIException as e:
        error_message = f"Unexpected error when retrieving user id:{user_id}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    if not user:
        return make_response(scim_error("User not found", 404), 404)

    db_user = app.db.find_user_by_id(user_id)
    if db_user:
        user["externalId"] = db_user.get("idp_id")
    else:
        app.logger.info("Okta user ID not found in the database for user with Looker ID %s", user["id"])

    app.logger.debug(user)
    return make_response(jsonify(user), 200)


@app.route("/scim/v2/Users", methods=["POST"])
@auth_required
@validate_json(ScimPayloadType.USER)
def create_user():
    """Create SCIM User"""

    username = request.json.get("userName")
    idp_id = request.json.get("externalId")

    try:
        user = app.appapi.create_user(raw_user=request.json, username=username)

    except ObjectAlreadyExists:
        error_message = f"User {username} already exists"
        app.logger.error(error_message, exc_info=True)
        return make_response(scim_error(error_message, 409), 409)

    except AppAPIException as e:
        error_message = f"Unexpected error when creating user {username}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    user["externalId"] = idp_id
    app.db.add_user(user["id"], idp_id)

    app.logger.debug(user)
    return make_response(jsonify(user), 201)


@app.route("/scim/v2/Users/<string:user_id>", methods=["PUT"])
@auth_required
@validate_json(ScimPayloadType.USER)
def update_user(user_id):
    """Update SCIM User"""

    username = request.json["userName"]
    idp_id = request.json.get("externalId")

    try:
        user = app.appapi.get_user(user_id)

    except AppAPIException as e:
        error_message = f"Unexpected error when retriving user id:{user_id}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    if not user:
        return make_response(scim_error("User not found", 404), 404)

    try:
        user = app.appapi.update_user(user_id, request.json, username)

    except AppAPIException as e:
        error_message = f"Unexpected error when updating user id:{user_id}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    user["externalId"] = idp_id
    if user.get("active"):
        app.db.add_user(user_id, idp_id)
    else:
        app.db.remove_user(user_id)

    app.logger.debug(user)
    return make_response(jsonify(user), 200)


@app.route("/scim/v2/Users/<string:user_id>", methods=["PATCH"])
@auth_required
@validate_json(ScimPayloadType.USER_PATCH)
def patch_user(user_id):
    """PATCH SCIM User"""

    # Note: In the future we might want to extended method to support more operations

    try:
        user = None
        for operation in request.json["Operations"]:
            if operation["op"] != "replace":
                error_message = f"SCIM PATCH method {operation['op']} not implemented"
                app.logger.error(error_message)
                return make_response(scim_error(error_message, 501), 501)

            is_active = operation["value"].get("active")
            if is_active is not None:
                user = app.appapi.change_user_state(user_id, is_active)

            if operation["value"].get("password"):
                error_message = "Okta is trying to update the password via SCIM PATCH. This is not implemented"
                app.logger.error(error_message)
                return make_response(scim_error(error_message, 501), 501)

        if not user:
            user = app.appapi.get_user(user_id)

    except AppAPIException as e:
        error_message = f"Unexpected error when patching user id:{user_id}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    if not user.get("active"):
        app.db.remove_user(user_id)

    return make_response(jsonify(user), 200)


@app.route("/scim/v2/Users/<string:user_id>", methods=["DELETE"])
@auth_required
def delete_user(user_id):
    """Delete SCIM User"""

    try:
        app.appapi.delete_user(user_id)

    except AppAPIException as e:
        error_message = f"Failed to delete the user {user_id}. Perhaps it is no longer there"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 404), 404)

    finally:
        app.db.remove_user(user_id)

    return make_response("", 204)


# SCIM Groups API + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + + +

# https://developer.okta.com/docs/api/openapi/okta-scim/guides/scim-20/#create-groups
@app.route("/scim/v2/Groups", methods=["POST"])
@auth_required
@validate_json(ScimPayloadType.GROUP)
def create_group():
    """Create SCIM Group"""

    try:
        group_name = request.json["displayName"]
        group = app.appapi.create_group(group_name)

        # Okta can create a group with members right away
        if "members" in request.json:
            group = app.appapi.update_group_membership(group["id"], request.json["members"])

    except AppAPIException as e:
        error_message = f"Unexpected error when creating group {group_name}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    app.logger.debug(group)
    return make_response(jsonify(group), 201)


# https://developer.okta.com/docs/api/openapi/okta-scim/guides/scim-20/#retrieve-groups
@app.route("/scim/v2/Groups", methods=["GET"])
@auth_required
def get_groups():
    """Get SCIM Groups"""

    start_index = request.args.get("startIndex", 1, type=int)
    offset = start_index - 1
    limit = request.args.get("count", 100, type=int)

    if "filter" in request.args:
        # This assumes Okta always uses filter to search for a single user as documented in https://developer.okta.com/docs/reference/scim/scim-20/
        m = re.match(r'displayName eq "(.*)"', request.args["filter"])
        if m:
            groupname = m.group(1)
        else:
            error_message = "Unexpected filter: " + request.args["filter"]
            app.logger.error(error_message)
            return make_response(scim_error(error_message, 501), 501)

        try:
            groups, total_group_count = app.appapi.search_groups(groupname)

        except AppAPIException as e:
            error_message = f"Unexpected error when searching for group {groupname}"
            app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
            return make_response(scim_error(error_message, 500), 500)
    else:
        try:
            groups, total_group_count = app.appapi.get_groups(limit, offset)

        except AppAPIException as e:
            error_message = "Unexpected error when retrieving groups"
            app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
            return make_response(scim_error(error_message, 500), 500)

    response = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total_group_count,
        "startIndex": start_index,
        "itemsPerPage": len(groups),
        "Resources": groups,
    }
    app.logger.debug(response)
    return make_response(jsonify(response), 200)


# https://developer.okta.com/docs/api/openapi/okta-scim/guides/scim-20/#retrieve-specific-groups
@app.route("/scim/v2/Groups/<string:group_id>", methods=["GET"])
@auth_required
def get_group(group_id):
    """Get SCIM Group"""

    try:
        group = app.appapi.get_group(group_id)

    except AppAPIException as e:
        error_message = f"Unexpected error when retrieving group id:{group_id}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    if not group:
        app.logger.warning("Group id:%s not found", group_id)
        abort(404)

    app.logger.debug(group)
    return make_response(jsonify(group), 200)


# https://developer.okta.com/docs/api/openapi/okta-scim/guides/scim-20/#update-a-specific-group-name
# https://developer.okta.com/docs/api/openapi/okta-scim/guides/scim-20/#update-specific-group-membership
def group_patch_ops(group_id, operations):
    """Helper function which processes group PATCH operations"""
    for oper in operations:
        if oper.get("op") == "replace":
            if oper.get("path") == "members":
                app.appapi.update_group_membership(group_id, oper.get("value", []))
            else:
                app.appapi.update_group_name(group_id, oper["value"]["displayName"])

        elif oper.get("op") == "add" and oper.get("path") == "members":
            for user in oper["value"]:
                app.appapi.add_group_member(group_id, user_id=user["value"])

        elif oper.get("op") == "remove":
            # This assumes Okta always uses filter to remove a single user as documented in https://developer.okta.com/docs/reference/scim/scim-20/
            m = re.match(r'members\[value eq "(.*)"\]', oper["path"])
            if m:
                user_id = m.group(1)
            else:
                error_message = "Unexpected filter in Groups op: " + oper["path"]
                app.logger.error(error_message)
                return error_message, 501

            app.appapi.remove_group_member(group_id, user_id)

    return None, None


@app.route("/scim/v2/Groups/<string:group_id>", methods=["PUT"])
@auth_required
@validate_json(ScimPayloadType.GROUP)
def update_group(group_id):
    """
    Okta AIW apps use PUT to update group information.
    """

    try:
        app.appapi.update_group_name(group_id, request.json["displayName"])
        app.appapi.update_group_membership(group_id, request.json.get("members", []))
        new_group = app.appapi.get_group(group_id)

    except AppAPIException as e:
        error_message = f"Unexpected error when updating group id:{group_id}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    app.logger.debug(new_group)
    return make_response(jsonify(new_group), 200)


@app.route("/scim/v2/Groups/<string:group_id>", methods=["PATCH"])
@auth_required
@validate_json(ScimPayloadType.GROUP_PATCH)
def patch_group(group_id):
    """
    Okta OIN apps use PUT to update group information.
    """

    try:
        r_msg, r_code = group_patch_ops(group_id, request.json.get("Operations", []))
        if r_msg:
            return make_response(scim_error(r_msg, r_code), r_code)

        new_group = app.appapi.get_group(group_id)

    except AppAPIException as e:
        error_message = f"Unexpected error when updating group id:{group_id}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    app.logger.debug(new_group)
    return make_response(jsonify(new_group), 200)


# https://developer.okta.com/docs/api/openapi/okta-scim/guides/scim-20/#delete-a-specific-group
@app.route("/scim/v2/Groups/<string:group_id>", methods=["DELETE"])
@auth_required
def delete_group(group_id):
    """Delete SCIM Group"""

    try:
        app.appapi.delete_group(group_id)

    except AppAPIException as e:
        error_message = f"Unable to delete group id:{group_id}"
        app.logger.error("%s. Reason: %s", error_message, e, exc_info=True)
        return make_response(scim_error(error_message, 500), 500)

    return make_response("", 204)


# Assuming debug session when running directly by python interpreter
if __name__ == "__main__":  # pragma: no cover
    app.logger.setLevel(logging.DEBUG)
    app.run(debug=True, host="::1", port=int(os.environ.get("PORT", 8080)))
    app.logger.info("App is now running locally by Python")
