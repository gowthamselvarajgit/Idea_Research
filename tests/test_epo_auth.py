"""Unit tests for EPOAuthClient using mocks."""

import base64
import json
from unittest import mock
import unittest
import urllib.error

from src.patents.epo_auth import (
    EPOAuthClient,
    EPOAuthError,
    EPOHTTPError,
    EPOMissingCredentialsError,
    EPONetworkError,
    EPOResponseError,
)


class TestEPOAuthClient(unittest.TestCase):
    """Test suite for EPO OAuth2 Client Credentials authentication."""

    def setUp(self):
        self.key = "mock_consumer_key"
        self.secret = "mock_consumer_secret"
        self.token_url = "https://ops.epo.org/3.2/auth/accesstoken"

    def test_successful_token_retrieval(self):
        """Verify successful token retrieval returns the access token string."""
        client = EPOAuthClient(
            consumer_key=self.key,
            consumer_secret=self.secret,
            token_url=self.token_url,
        )

        mock_payload = {
            "access_token": "valid_epo_bearer_token_abc123",
            "token_type": "Bearer",
            "expires_in": "1200",
        }
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            token = client.get_access_token()
            self.assertEqual(token, "valid_epo_bearer_token_abc123")

    def test_correct_token_url_and_request_attributes(self):
        """Verify the request targets the configured token URL with correct headers and body."""
        client = EPOAuthClient(
            consumer_key=self.key,
            consumer_secret=self.secret,
            token_url=self.token_url,
        )

        captured_request = None

        def fake_urlopen(req, timeout):
            nonlocal captured_request
            captured_request = req
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = b'{"access_token": "token123"}'
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.get_access_token()

        self.assertIsNotNone(captured_request)
        self.assertEqual(captured_request.full_url, self.token_url)
        self.assertEqual(captured_request.get_method(), "POST")

        # Verify Basic Authentication header
        expected_credentials = f"{self.key}:{self.secret}".encode("utf-8")
        expected_auth = f"Basic {base64.b64encode(expected_credentials).decode('utf-8')}"
        self.assertEqual(captured_request.headers.get("Authorization"), expected_auth)

        # Verify grant_type=client_credentials in body
        self.assertEqual(captured_request.data.decode("utf-8"), "grant_type=client_credentials")

    def test_missing_credentials_fail_clearly(self):
        """Verify EPOMissingCredentialsError is raised when key or secret is absent."""
        # Missing key
        client_no_key = EPOAuthClient(consumer_key=None, consumer_secret=self.secret)
        client_no_key.consumer_key = None
        with self.assertRaises(EPOMissingCredentialsError) as ctx:
            client_no_key.get_access_token()
        self.assertIn("Consumer Key is missing", str(ctx.exception))

        # Missing secret
        client_no_secret = EPOAuthClient(consumer_key=self.key, consumer_secret=None)
        client_no_secret.consumer_secret = None
        with self.assertRaises(EPOMissingCredentialsError) as ctx:
            client_no_secret.get_access_token()
        self.assertIn("Consumer Secret is missing", str(ctx.exception))

    def test_http_error_handling(self):
        """Verify HTTP 400/401/500 errors are wrapped in EPOHTTPError."""
        client = EPOAuthClient(consumer_key=self.key, consumer_secret=self.secret)

        http_err = urllib.error.HTTPError(
            url=self.token_url,
            code=401,
            msg="Unauthorized",
            hdrs={},  # type: ignore
            fp=None,  # type: ignore
        )

        with mock.patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(EPOHTTPError) as ctx:
                client.get_access_token()

            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIsInstance(ctx.exception, EPOAuthError)

    def test_malformed_token_response_handling(self):
        """Verify EPOResponseError is raised on non-JSON or missing access_token."""
        client = EPOAuthClient(consumer_key=self.key, consumer_secret=self.secret)

        # Case 1: Non-JSON response
        mock_resp_invalid_json = mock.MagicMock()
        mock_resp_invalid_json.read.return_value = b"<html>Server Error</html>"
        mock_resp_invalid_json.__enter__.return_value = mock_resp_invalid_json

        with mock.patch("urllib.request.urlopen", return_value=mock_resp_invalid_json):
            with self.assertRaises(EPOResponseError):
                client.get_access_token()

        # Case 2: JSON missing access_token
        mock_resp_missing_key = mock.MagicMock()
        mock_resp_missing_key.read.return_value = b'{"error": "invalid_client"}'
        mock_resp_missing_key.__enter__.return_value = mock_resp_missing_key

        with mock.patch("urllib.request.urlopen", return_value=mock_resp_missing_key):
            with self.assertRaises(EPOResponseError):
                client.get_access_token()

    def test_network_error_handling(self):
        """Verify URLError and TimeoutError are wrapped in EPONetworkError."""
        client = EPOAuthClient(consumer_key=self.key, consumer_secret=self.secret)

        # URLError
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("DNS failed")):
            with self.assertRaises(EPONetworkError):
                client.get_access_token()

        # TimeoutError
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("Timeout")):
            with self.assertRaises(EPONetworkError):
                client.get_access_token()


if __name__ == "__main__":
    unittest.main()
