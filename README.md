# Okta Looker SCIM Bridge

**This project is no longer maintained. Use at your own risk**

Okta Looker SCIM Bridge is a proxy service which translates SCIM API calls made by Okta
to Looker API calls. The service provides full provisioning capability for users and groups.
The service is loosely inspired by [looker-scim-proxy](https://github.com/looker-open-source/looker-scim-proxy).

Supported operations:
- User creation
- User deactivation
- User attribute changes, including username (both PUT and PATCH methods supported)
- User deletion (Okta does not use this endpoint)
- Group creation
- Group name and membership updates (both PUT and PATCH methods supported)
- Group deletion

Supported user attributes:
- username (equals email in Looker context)
- email (equals username in Looker context)
- first name
- last name
- display name
- locale

Okta Looker SCIM Bridge implements a subset of SCIM 2.0 functionality. It is not a fully
compliant SCIM 2.0 interface. The feature set is aligned to SCIM functionality [used by Okta](https://developer.okta.com/docs/api/openapi/okta-scim/guides/scim-20/).

Known limitations (Okta context):
- Password syncing is not supported.


## Dependency management

The project uses `setuptools` to generate `requirements.txt` for `pip`.

### Updating dependencies for Cloud Run deployment

Suggested process:

1. Remove `requirements.txt` file
2. Update dependency versions in `pyproject.toml`
3. Generate a new `requirements.txt` file with `pip-compile --output-file=requirements.txt pyproject.toml`

### Manual dependency install

Add or remove dependencies in pyproject.toml. Use pip-compile to generate requirements.txt:
~~~zsh
pip install --upgrade pip && pip install --upgrade pip-tools
pip-compile --output-file=requirements.txt pyproject.toml
pip install .  # install main app dependencies
pip install -e '.[lint]'  # install linters
~~~

`pip-compile` is part of [pip-tools](https://pypi.org/project/pip-tools/) package you need to have installed.


## Local development

Create and activate a virtual environment.
~~~zsh
python -m venv venv
source venv/bin/activate
pip install .
~~~

Configure Looker API access via looker.ini file or environment variables.
See Looker [page](https://pypi.org/project/looker-sdk/) on PyPI for more informatinon.

Following options must be configured:
- base_url
- client_id
- client_secret

Set `SCIM_API_KEY` as an environment variable.
You can set `CONFIGURATION_TYPE` in the environment either to `local` or `environ` (defaults to `local`) depending on where the Looker configuration should be loaded from.

Run the server locally
~~~zsh
cd app
SCIM_API_KEY=slowpoke gunicorn --bind "[::1]:8080" app:app
~~~
