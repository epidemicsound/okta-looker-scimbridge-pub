# e2e test suite

**The e2e test suite is not usable as-is. Some values were replaced with `<MISSING` placeholder since they referenced resources specific to a particular environment.**

There is a Python script `e2e_app.py` which uses functions from `e2e_library.py` to
execute a series of e2e tests between Okta and Looker.

User and group information is pushed in the following way: Okta -> Okta Looker SCIM Bridge -> Looker.
Tests do not directly interact with Okta Looker SCIM Bridge, which is treated as a black box.

Test functions use:
- Okta API to manipulate users, groups, user assignments, and group push
mappings on the Okta side with the intention to cause changes in Looker (downstream).
- Looker API to see what the state of users and groups is in Looker after the changes caused by Okta (upstream).


## Test apps

The test suite is run for two test apps configured in the Okta environment in sequence:
- Looker SCIM Bridge Custom
- Looker SCIM Bridge OIN

The Okta app type determines which HTTP methods are used during user and group update actions.
Read more about this in [Okta and SCIM Version 2.0](https://developer.okta.com/docs/api/openapi/okta-scim/guides/scim-20/).
The intention here is to support both AIW and OIN apps.


## Test process

Environment preparation:
1. Set up the desired initial state in Okta.
2. Set up the desired initial state in Looker.

Initial push:
1. Assign test users to the Okta app.
2. Create group push mappings in the Okta app using test groups.
3. Adjust group memberships, adding and removing users.
4. Check Okta user assignments and group push mappings to see if there are no errors.
5. Check the state of users and groups in Looker to see if all the changes have been successfully pushed via SCIM.

Push changes:
1. Change values in user assignments such as:
  - givenName
  - login (username)
  - locale
2. Rename one of the test groups (X->Y).
3. Rename one of the other test groups back and forth (A->B->A).
4. Check the state of users and groups in Looker to see if all the changes have been successfully pushed via SCIM.

Clean up:
1. Remove all Okta user assignments and group push mappings from the Okta test app.
2. Check the state of users and groups in Looker to see if all the changes have been successfully pushed via SCIM.
3. Do additional clean up in Looker.
