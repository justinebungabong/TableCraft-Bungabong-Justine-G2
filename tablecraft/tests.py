import os
from unittest.mock import patch

from django.test import SimpleTestCase

from tablecraft.settings import db_conn_max_age


class DatabaseConnectionSettingsTests(SimpleTestCase):
    def test_default_closes_connections_after_each_request(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(db_conn_max_age(), 0)

    def test_environment_override_is_never_negative(self):
        with patch.dict(os.environ, {"DB_CONN_MAX_AGE": "-5"}, clear=True):
            self.assertEqual(db_conn_max_age(), 0)

    def test_environment_override_is_honoured(self):
        with patch.dict(os.environ, {"DB_CONN_MAX_AGE": "30"}, clear=True):
            self.assertEqual(db_conn_max_age(), 30)
