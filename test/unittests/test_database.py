"""
Set of unit tests for app/database.py
"""

import pytest

from app.database import (DictDatabase, GoogleDatastore, GoogleFirestore,
                          datastore, firestore)


# Fixtures for GoogleFirestore - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
@pytest.fixture(autouse=True)
def mock_firestore_client(mocker):
    """Mocks the firestore.Client constructor and returns the mock instance."""

    mock_client = mocker.MagicMock(spec=firestore.Client)

    mocker.patch("app.database.firestore.Client", return_value=mock_client)
    return mock_client


@pytest.fixture
def firestore_db():
    """Returns an instance of GoogleFirestore with a mocked client."""
    return GoogleFirestore(database_name="test-db")


def test_firestore_add_user(firestore_db, mock_firestore_client):
    """Test that add_user calls .collection().document().set() correctly."""
    firestore_db.add_user("looker123", "idp456")

    mock_collection = mock_firestore_client.collection
    mock_doc = mock_collection.return_value.document
    mock_set = mock_doc.return_value.set

    mock_collection.assert_called_once_with("users")
    mock_doc.assert_called_once_with("looker123")
    mock_set.assert_called_once_with({
        "idp_id": "idp456",
        "looker_id": "looker123"
    })


# Tests for GoogleFirestore - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def test_firestore_remove_user(firestore_db, mock_firestore_client):
    """Test that remove_user calls .collection().document().delete() correctly."""
    firestore_db.remove_user("looker123")

    mock_collection = mock_firestore_client.collection
    mock_doc = mock_collection.return_value.document
    mock_delete = mock_doc.return_value.delete

    mock_collection.assert_called_once_with("users")
    mock_doc.assert_called_once_with("looker123")
    mock_delete.assert_called_once_with()


def test_firestore_find_user_by_id_found(mocker, firestore_db, mock_firestore_client):
    """Test find_user_by_id when the document exists."""
    mock_doc = mocker.Mock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"idp_id": "idp456", "looker_id": "looker123"}

    mock_firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

    result = firestore_db.find_user_by_id("looker123")

    assert result == {"idp_id": "idp456", "looker_id": "looker123"}
    mock_firestore_client.collection.assert_called_with("users")
    mock_firestore_client.collection.return_value.document.assert_called_with("looker123")


def test_firestore_find_user_by_id_not_found(mocker, firestore_db, mock_firestore_client):
    """Test find_user_by_id when the document does not exist."""
    mock_doc = mocker.Mock()
    mock_doc.exists = False

    mock_firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

    result = firestore_db.find_user_by_id("looker123")

    assert result is None


def test_firestore_find_users_by_idp_id(mocker, firestore_db, mock_firestore_client):
    """Test finding users by idp_id, which involves a query."""
    mock_doc1 = mocker.Mock()
    mock_doc1.to_dict.return_value = {"idp_id": "idp456", "looker_id": "looker123"}
    mock_doc2 = mocker.Mock()
    mock_doc2.to_dict.return_value = {"idp_id": "idp456", "looker_id": "looker789"}

    mock_query = mock_firestore_client.collection.return_value.where.return_value
    mock_query.stream.return_value = [mock_doc1, mock_doc2]

    result = firestore_db.find_users_by_idp_id("idp456")

    assert result == [
        {"idp_id": "idp456", "looker_id": "looker123"},
        {"idp_id": "idp456", "looker_id": "looker789"}
    ]
    mock_firestore_client.collection.return_value.where.assert_called_once_with(
        filter=mocker.ANY
    )


# Fixtures for GoogleDatastore - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
@pytest.fixture(autouse=True)
def mock_datastore_client(mocker):
    """Mocks the datastore.Client constructor and returns the mock instance."""

    # CHANGED: Get MagicMock directly from the mocker fixture
    mock_client = mocker.MagicMock(spec=datastore.Client)

    mocker.patch("app.database.datastore.Client", return_value=mock_client)
    return mock_client


@pytest.fixture
def datastore_db():
    """Returns an instance of GoogleDatastore with a mocked client."""
    return GoogleDatastore(database_name="test-db")


# Tests for GoogleDatastore - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def test_datastore_add_user(mocker, datastore_db):
    """Test add_user by checking its call to the _add_entity helper."""
    mock_add_helper = mocker.patch.object(datastore_db, "_add_entity")

    datastore_db.add_user("looker123", "idp456")

    expected_properties = {
        "idp_id": "idp456",
        "looker_id": "looker123"
    }
    mock_add_helper.assert_called_once_with(
        "User", "looker123", expected_properties
    )


def test_datastore_remove_user(mocker, datastore_db):
    """Test remove_user by checking its call to the _delete_entity helper."""
    mock_delete_helper = mocker.patch.object(datastore_db, "_delete_entity")

    datastore_db.remove_user("looker123")

    mock_delete_helper.assert_called_once_with("User", "looker123")


def test_datastore_find_user_by_id_found(mocker, datastore_db):
    """Test find_user_by_id by checking its call to the _get_entity_by_key helper."""
    expected_entity = {"idp_id": "idp456", "looker_id": "looker123"}
    mock_get_helper = mocker.patch.object(
        datastore_db,
        "_get_entity_by_key",
        return_value=expected_entity
    )

    result = datastore_db.find_user_by_id("looker123")

    assert result == expected_entity
    mock_get_helper.assert_called_once_with("User", "looker123")


def test_datastore_find_user_by_id_not_found(mocker, datastore_db):
    """Test find_user_by_id when the helper returns None."""
    mock_get_helper = mocker.patch.object(
        datastore_db,
        "_get_entity_by_key",
        return_value=None
    )

    result = datastore_db.find_user_by_id("looker123")

    assert result is None
    mock_get_helper.assert_called_once_with("User", "looker123")


def test_datastore_find_users_by_idp_id(mocker, datastore_db):
    """Test find_users_by_idp_id by checking its call to the _query_entities helper."""
    mock_entities = [
        {"idp_id": "idp456", "looker_id": "looker123"},
        {"idp_id": "idp456", "looker_id": "looker789"}
    ]
    mock_query_helper = mocker.patch.object(
        datastore_db,
        "_query_entities",
        return_value=mock_entities
    )

    result = datastore_db.find_users_by_idp_id("idp456")

    assert result == mock_entities
    mock_query_helper.assert_called_once_with("User", "idp_id", "idp456")


# Tests for GoogleDatastore private methods - - - - - - - - - - - - - - - - - - - - - - -
def test_datastore_private_get_entity_by_key(datastore_db, mock_datastore_client):
    """Tests the _get_entity_by_key helper."""
    mock_key = "mock-key"
    mock_entity = {"id": "looker123"}

    mock_datastore_client.key.return_value = mock_key
    mock_datastore_client.get.return_value = mock_entity

    result = datastore_db._get_entity_by_key("User", "looker123")

    assert result == mock_entity
    mock_datastore_client.key.assert_called_once_with("User", "looker123")
    mock_datastore_client.get.assert_called_once_with(mock_key)


def test_datastore_private_add_entity(mocker, datastore_db, mock_datastore_client):
    """Tests the _add_entity helper."""
    mock_key = "mock-key"
    mock_entity_instance = mocker.Mock()

    # Mock the datastore.Entity constructor
    mock_entity_constructor = mocker.patch(
        "app.database.datastore.Entity",
        return_value=mock_entity_instance
    )

    mock_datastore_client.key.return_value = mock_key

    properties = {"idp_id": "idp456", "looker_id": "looker123"}
    datastore_db._add_entity("User", "looker123", properties)

    mock_datastore_client.key.assert_called_once_with("User", "looker123")

    mock_entity_constructor.assert_called_once_with(key=mock_key)

    mock_entity_instance.update.assert_called_once_with(properties)

    mock_datastore_client.put.assert_called_once_with(mock_entity_instance)


def test_datastore_private_query_entities(mocker, datastore_db, mock_datastore_client):
    """Tests the _query_entities helper."""
    mock_query = mocker.MagicMock()
    mock_datastore_client.query.return_value = mock_query

    mock_results = [{"id": "looker123"}]
    mock_query.fetch.return_value = mock_results

    results = datastore_db._query_entities("User", "idp_id", "idp456")

    assert results == mock_results

    mock_datastore_client.query.assert_called_once_with(kind="User")

    mock_query.add_filter.assert_called_once_with(
        filter=mocker.ANY  # We use ANY to avoid importing PropertyFilter
    )

    mock_query.fetch.assert_called_once_with()


def test_datastore_private_delete_entity(datastore_db, mock_datastore_client):
    """Tests the _delete_entity helper."""
    mock_key = "mock-key"
    mock_datastore_client.key.return_value = mock_key

    datastore_db._delete_entity("User", "looker123")

    mock_datastore_client.key.assert_called_once_with("User", "looker123")
    mock_datastore_client.delete.assert_called_once_with(mock_key)


def test_datastore_private_get_all_entities(mocker, datastore_db, mock_datastore_client):
    """Tests the _get_all_entities helper."""
    mock_query = mocker.MagicMock()
    mock_datastore_client.query.return_value = mock_query

    mock_results = [{"id": "looker123"}, {"id": "looker456"}]
    mock_query.fetch.return_value = mock_results

    results = datastore_db._get_all_entities("User")

    assert results == mock_results
    mock_datastore_client.query.assert_called_once_with(kind="User")
    mock_query.fetch.assert_called_once_with()


def test_datastore_private_get_entity_count(mocker, datastore_db):
    """Tests the _get_entity_count helper."""
    # Patch the *other* private method this one calls
    mocker.patch.object(
        datastore_db,
        "_get_all_entities",
        return_value=["item1", "item2", "item3"]
    )

    count = datastore_db._get_entity_count("User")

    assert count == 3
    datastore_db._get_all_entities.assert_called_once_with("User")


# Tests for DictDatabase - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
@pytest.fixture
def testdb():
    """Returns an instance of DictDatabase"""
    return DictDatabase()


def test_testdb_add_user(testdb):
    """Test add_user by calling it"""

    testdb.add_user("looker123", "idp456")

    expected_properties = {
        "idp_id": "idp456",
        "looker_id": "looker123"
    }

    assert testdb.db.get("looker123") == expected_properties


def test_testdb_remove_user(testdb):
    """Test remove_user by calling it"""

    user_to_delete = {
        "idp_id": "idp456",
        "looker_id": "looker123"
    }
    testdb.db["looker123"] = user_to_delete

    testdb.remove_user("looker123")

    assert testdb.db.get("looker123") is None


def test_testdb_find_user_by_id_found(testdb):
    """Test find_user_by_id by calling it"""

    expected_entity = {"idp_id": "idp456", "looker_id": "looker123"}
    testdb.db["looker123"] = expected_entity

    result = testdb.find_user_by_id("looker123")

    assert result == expected_entity


def test_testdb_find_user_by_id_not_found(testdb):
    """Test find_user_by_id when the helper returns None."""

    result = testdb.find_user_by_id("looker123")

    assert result is None


def test_testdb_find_users_by_idp_id(testdb):
    """Test find_users_by_idp_id by calling it"""
    mock_entities = [
        {"idp_id": "idp456", "looker_id": "looker123"},
        {"idp_id": "idp456", "looker_id": "looker789"}
    ]
    testdb.db["looker123"] = {"idp_id": "idp456", "looker_id": "looker123"}
    testdb.db["looker789"] = {"idp_id": "idp456", "looker_id": "looker789"}

    result = testdb.find_users_by_idp_id("idp456")

    assert result == mock_entities
