"""
Database code for storing Okta ID <-> Looker ID in various DB backends.
"""

import abc

from google.cloud import datastore, firestore
from google.cloud.datastore.query import PropertyFilter
from google.cloud.firestore_v1.base_query import FieldFilter


class DatabaseBackend(abc.ABC):
    """Database backend parent class"""

    @abc.abstractmethod
    def add_user(self, looker_id, idp_id):
        pass

    @abc.abstractmethod
    def remove_user(self, looker_id):
        pass

    @abc.abstractmethod
    def find_user_by_id(self, looker_id):
        pass

    @abc.abstractmethod
    def find_users_by_idp_id(self, idp_id):
        pass


class DictDatabase(DatabaseBackend):
    """Dictionary database for local testing"""

    def __init__(self):
        self.db = {}

    def add_user(self, looker_id, idp_id):
        self.db[looker_id] = {"idp_id": idp_id, "looker_id": looker_id}

    def remove_user(self, looker_id):
        self.db.pop(looker_id, None)

    def find_user_by_id(self, looker_id):
        return self.db.get(looker_id)

    def find_users_by_idp_id(self, idp_id):
        users = []
        for _, value in self.db.items():
            if value["idp_id"] == idp_id:
                users.append(value)
        return users


class GoogleFirestore(DatabaseBackend):
    """Google Firestore in native mode database backend"""

    user_collection = "users"

    def __init__(self, database_name):
        self.ds = firestore.Client(database=database_name)

    def add_user(self, looker_id, idp_id):
        attributes = {"idp_id": idp_id, "looker_id": looker_id}
        self.ds.collection(self.user_collection).document(looker_id).set(attributes)

    def remove_user(self, looker_id):
        self.ds.collection(self.user_collection).document(looker_id).delete()

    def find_user_by_id(self, looker_id):
        doc_ref = self.ds.collection(self.user_collection).document(looker_id)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()

        return None

    def find_users_by_idp_id(self, idp_id):
        collection_ref = self.ds.collection(self.user_collection)
        query_ref = collection_ref.where(filter=FieldFilter("idp_id", "==", idp_id))
        docs = query_ref.stream()
        users = []
        for doc in docs:
            users.append(doc.to_dict())

        return users


class GoogleDatastore(DatabaseBackend):
    """Google Firestore in datastore mode database backend"""

    user_entity = "User"

    def __init__(self, database_name):
        self.ds = datastore.Client(database=database_name)

    def _get_entity_by_key(self, kind, identifier):
        entity_key = self.ds.key(kind, identifier)
        entity = self.ds.get(entity_key)
        return entity

    def _add_entity(self, kind, name, properties):
        entity_key = self.ds.key(kind, name)
        entity = datastore.Entity(key=entity_key)
        entity.update(properties)
        self.ds.put(entity)

    # Kept only for future reference. Very ineficient with real databases.
    def _get_all_entities(self, kind):
        query = self.ds.query(kind=kind)
        entities = list(query.fetch())
        return entities

    # Kept only for future reference. Very ineficient with real databases.
    def _get_entity_count(self, kind):
        entities = self._get_all_entities(kind)
        entity_count = len(entities)
        return entity_count

    def _query_entities(self, kind, property_name, property_value):
        query = self.ds.query(kind=kind)
        query.add_filter(filter=PropertyFilter(property_name, "=", property_value))

        results = list(query.fetch())
        return results

    def _delete_entity(self, kind, entity_id):
        entity_key = self.ds.key(kind, entity_id)
        self.ds.delete(entity_key)

    def add_user(self, looker_id, idp_id):
        name = looker_id
        properties = {
            "idp_id": idp_id,
            "looker_id": looker_id
        }
        self._add_entity(self.user_entity, name, properties)

    def remove_user(self, looker_id):
        self._delete_entity(self.user_entity, looker_id)

    def find_user_by_id(self, looker_id):
        entity = self._get_entity_by_key(self.user_entity, looker_id)
        if entity:
            return dict(entity)

        return None

    def find_users_by_idp_id(self, idp_id):
        entities = self._query_entities(self.user_entity, "idp_id", idp_id)
        users = []

        for entity in entities:
            users.append(dict(entity))

        return users
