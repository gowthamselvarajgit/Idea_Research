"""Tests for EPO Open Patent Services (OPS) configuration settings."""

import os
from unittest import mock
import unittest

import config.settings as settings


class TestEPOConfig(unittest.TestCase):
    """Test suite for EPO configuration and environment variable loading."""

    def test_default_base_url(self):
        """Verify the base URL defaults to https://ops.epo.org/3.2/rest-services when unset."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EPO_API_BASE_URL", None)
            conf = settings.get_epo_config()
            self.assertEqual(conf["base_url"], "https://ops.epo.org/3.2/rest-services")

    def test_default_token_url(self):
        """Verify the token URL defaults to https://ops.epo.org/3.2/auth/accesstoken when unset."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EPO_TOKEN_URL", None)
            conf = settings.get_epo_config()
            self.assertEqual(conf["token_url"], "https://ops.epo.org/3.2/auth/accesstoken")

    def test_environment_overrides(self):
        """Verify custom EPO URLs can be loaded from the environment."""
        custom_base = "https://custom.epo.org/rest"
        custom_token = "https://custom.epo.org/token"
        with mock.patch.dict(
            os.environ,
            {"EPO_API_BASE_URL": custom_base, "EPO_TOKEN_URL": custom_token},
        ):
            conf = settings.get_epo_config()
            self.assertEqual(conf["base_url"], custom_base)
            self.assertEqual(conf["token_url"], custom_token)

    def test_credentials_read_from_environment(self):
        """Verify Consumer Key and Consumer Secret are read from environment."""
        mock_key = "test_epo_consumer_key_123"
        mock_secret = "test_epo_consumer_secret_456"
        with mock.patch.dict(
            os.environ,
            {"EPO_CONSUMER_KEY": mock_key, "EPO_CONSUMER_SECRET": mock_secret},
        ):
            conf = settings.get_epo_config()
            self.assertEqual(conf["consumer_key"], mock_key)
            self.assertEqual(conf["consumer_secret"], mock_secret)

    def test_missing_credentials_return_none_without_exception(self):
        """Verify missing credentials return None without raising an exception."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EPO_CONSUMER_KEY", None)
            os.environ.pop("EPO_CONSUMER_SECRET", None)
            conf = settings.get_epo_config()
            self.assertIsNone(conf["consumer_key"])
            self.assertIsNone(conf["consumer_secret"])


if __name__ == "__main__":
    unittest.main()
