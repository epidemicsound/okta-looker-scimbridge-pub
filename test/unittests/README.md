# Unit tests

Unit tests are created using the `pytest` library. Individual tests can employ either one or both state-based and behavior-based approaches.


`pytest` can be run locally like this:

```
APP_ENV=test PYTHONPATH=. pytest -vv --cov=app --cov-report=term-missing .
```

Unit tests are run as part of several GitHub workflows in this repo.
