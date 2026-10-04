"""Tests for USPTO API configuration settings."""

import importlib
import os
import unittest
from unittest import mock

import config.settings as settings


class TestUSPTOConfig(unittest.TestCase):
    """Test suite for USPTO configuration and environment variable loading."""

    def test_default_base_url(self):
        """Verify the base URL defaults to https://api.uspto.gov/api/v1 when unset."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("USPTO_API_BASE_URL", None)
            conf = settings.get_uspto_config()
            self.assertEqual(conf["base_url"], "https://api.uspto.gov/api/v1")

    def test_custom_base_url_from_env(self):
        """Verify custom USPTO_API_BASE_URL can be loaded from environment."""
        custom_url = "https://custom.api.uspto.gov/v1"
        with mock.patch.dict(os.environ, {"USPTO_API_BASE_URL": custom_url}):
            conf = settings.get_uspto_config()
            self.assertEqual(conf["base_url"], custom_url)

    def test_api_key_read_from_environment(self):
        """Verify the API key is read from USPTO_API_KEY without requiring real credentials."""
        mock_key = "test_uspto_mock_key_abc123"
        with mock.patch.dict(os.environ, {"USPTO_API_KEY": mock_key}):
            conf = settings.get_uspto_config()
            self.assertEqual(conf["api_key"], mock_key)

    def test_missing_api_key_returns_none_without_error(self):
        """Verify that when no API key is set, None is returned without raising errors."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("USPTO_API_KEY", None)
            conf = settings.get_uspto_config()
            self.assertIsNone(conf["api_key"])


if __name__ == "__main__":
    unittest.main()
