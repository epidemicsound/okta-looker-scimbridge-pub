"""
Set of unit tests for app/helpers.py
"""

from app.helpers import access_secret_credential


def test_access_secret_credential(mocker):
    """
    Tests that the secret helper correctly calls the GCP client
    and decodes the response.
    """

    test_project = "my-gcp-project"
    test_secret_name = "my-db-password"
    expected_secret_string = "s3cure_p@ssw0rd!"
    expected_secret_bytes = expected_secret_string.encode("UTF-8")

    mock_response = mocker.Mock()
    mock_response.payload.data = expected_secret_bytes

    mock_client_instance = mocker.Mock()
    mock_client_instance.access_secret_version.return_value = mock_response

    mock_client_constructor = mocker.patch(
        "app.helpers.secretmanager.SecretManagerServiceClient",
        return_value=mock_client_instance
    )

    result = access_secret_credential(test_project, test_secret_name)

    # 1. Check that the final decoded string is correct
    assert result == expected_secret_string

    # 2. Check that the client was instantiated
    mock_client_constructor.assert_called_once_with()

    # 3. Check that the client's method was called with the correctly formatted name
    expected_name_arg = f"projects/{test_project}/secrets/{test_secret_name}/versions/latest"
    mock_client_instance.access_secret_version.assert_called_once_with(
        name=expected_name_arg
    )
