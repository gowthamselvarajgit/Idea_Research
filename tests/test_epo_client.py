"""Unit tests for EPOClient using mocks."""

from unittest import mock
import unittest
import urllib.error

from src.patents.base_client import BasePatentClient
from src.patents.epo_auth import EPOAuthClient, EPOMissingCredentialsError
from src.patents.epo_client import (
    EPOClient,
    EPOClientAuthenticationError,
    EPOClientError,
    EPOClientHTTPError,
    EPOClientNetworkError,
    EPOClientResponseError,
)


class TestEPOClient(unittest.TestCase):
    """Test suite for EPOClient search, pagination, headers, and error handling."""

    def setUp(self):
        self.mock_auth = mock.MagicMock(spec=EPOAuthClient)
        self.mock_auth.get_access_token.return_value = "mock_bearer_token_123"
        self.client = EPOClient(auth_client=self.mock_auth)

    def test_client_is_instance_of_base_client(self):
        """Verify EPOClient conforms to BasePatentClient."""
        self.assertIsInstance(self.client, BasePatentClient)

    def test_successful_search_returns_raw_payload(self):
        """Verify successful search returns the raw response string."""
        raw_xml = "<ops:world-patent-data><ops:biblio-search/></ops:world-patent-data>"
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = raw_xml.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            result = self.client.search(query='ta="solid state battery"', max_results=10)
            self.assertEqual(result, raw_xml)

    def test_authorization_bearer_header_is_sent(self):
        """Verify Authorization: Bearer {token} header is attached to request."""
        captured_request = None

        def fake_urlopen(req, timeout):
            nonlocal captured_request
            captured_request = req
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = b"<xml>data</xml>"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.client.search(query='ta="battery"')

        self.assertIsNotNone(captured_request)
        self.assertEqual(captured_request.headers.get("Authorization"), "Bearer mock_bearer_token_123")
        self.assertEqual(captured_request.headers.get("Accept"), "application/xml")

    def test_cql_query_is_passed_correctly(self):
        """Verify CQL query string is encoded and passed in request URL."""
        captured_request = None

        def fake_urlopen(req, timeout):
            nonlocal captured_request
            captured_request = req
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = b"<xml>data</xml>"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        cql_query = 'ta="lithium" AND pa="Tesla"'
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.client.search(query=cql_query)

        self.assertIn("q=ta%3D%22lithium%22+AND+pa%3D%22Tesla%22", captured_request.full_url)
        self.assertIn("/published-data/search/abstract,biblio", captured_request.full_url)

    def test_result_range_and_count_passed_correctly(self):
        """Verify result range is correctly calculated and passed."""
        captured_request = None

        def fake_urlopen(req, timeout):
            nonlocal captured_request
            captured_request = req
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = b"<xml>data</xml>"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.client.search(query='ta="battery"', max_results=25, start_index=11)

        self.assertIn("Range=11-35", captured_request.full_url)
        self.assertEqual(captured_request.headers.get("X-ops-range"), "11-35")

    def test_maximum_result_limit_enforced(self):
        """Verify max_results is capped at safe maximum (100)."""
        captured_request = None

        def fake_urlopen(req, timeout):
            nonlocal captured_request
            captured_request = req
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = b"<xml>data</xml>"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.client.search(query='ta="battery"', max_results=500, start_index=1)

        # 1 to 100
        self.assertIn("Range=1-100", captured_request.full_url)
        self.assertEqual(captured_request.headers.get("X-ops-range"), "1-100")

    def test_empty_query_returns_empty_string_without_network_call(self):
        """Verify empty/blank query returns empty string immediately."""
        self.assertEqual(self.client.search(""), "")
        self.assertEqual(self.client.search("   "), "")
        self.mock_auth.get_access_token.assert_not_called()

    def test_authentication_failure_handled(self):
        """Verify authentication failures are caught and raised as EPOClientAuthenticationError."""
        # 1. Failure during token acquisition
        self.mock_auth.get_access_token.side_effect = EPOMissingCredentialsError("No credentials")
        with self.assertRaises(EPOClientAuthenticationError):
            self.client.search(query='ta="battery"')

        # 2. HTTP 401 on search request
        self.mock_auth.get_access_token.side_effect = None
        self.mock_auth.get_access_token.return_value = "expired_or_invalid_token"

        http_401 = urllib.error.HTTPError(
            url="https://ops.epo.org/3.2/rest-services/published-data/search/abstract,biblio",
            code=401,
            msg="Unauthorized",
            hdrs={},  # type: ignore
            fp=None,  # type: ignore
        )

        with mock.patch("urllib.request.urlopen", side_effect=http_401):
            with self.assertRaises(EPOClientAuthenticationError):
                self.client.search(query='ta="battery"')

    def test_http_error_handled(self):
        """Verify non-2xx HTTP errors (e.g. 500, 404) raise EPOClientHTTPError."""
        http_500 = urllib.error.HTTPError(
            url="https://ops.epo.org/3.2/rest-services/published-data/search/abstract,biblio",
            code=500,
            msg="Internal Server Error",
            hdrs={},  # type: ignore
            fp=None,  # type: ignore
        )

        with mock.patch("urllib.request.urlopen", side_effect=http_500):
            with self.assertRaises(EPOClientHTTPError) as ctx:
                self.client.search(query='ta="battery"')

            self.assertEqual(ctx.exception.status_code, 500)
            self.assertIsInstance(ctx.exception, EPOClientError)

    def test_network_error_handled(self):
        """Verify URLError and TimeoutError raise EPOClientNetworkError."""
        # URLError
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            with self.assertRaises(EPOClientNetworkError):
                self.client.search(query='ta="battery"')

        # TimeoutError
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
            with self.assertRaises(EPOClientNetworkError):
                self.client.search(query='ta="battery"')

    def test_malformed_empty_response_handled(self):
        """Verify empty response body raises EPOClientResponseError."""
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__.return_value = mock_resp

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            with self.assertRaises(EPOClientResponseError):
                self.client.search(query='ta="battery"')


if __name__ == "__main__":
    unittest.main()
