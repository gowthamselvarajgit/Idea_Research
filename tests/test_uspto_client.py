"""Unit tests for USPTOClient structure and contract using mocks."""

import json
from unittest import mock
import unittest
import urllib.error

from src.patents.base_client import BasePatentClient
from src.patents.uspto_client import (
    USPTOClient,
    USPTOClientError,
    USPTOHTTPError,
    USPTOMissingAPIKeyError,
    USPTONetworkError,
    USPTOResponseError,
)


class TestUSPTOClient(unittest.TestCase):
    """Test suite for USPTOClient contract, configuration, and mock-based error handling."""

    def test_construction_without_api_key(self):
        """Verify client can be constructed without a real API key."""
        client = USPTOClient(api_key=None)
        self.assertIsInstance(client, BasePatentClient)
        self.assertEqual(client.base_url, "https://api.uspto.gov/api/v1")

    def test_missing_credentials_handled_clearly(self):
        """Verify search() raises USPTOMissingAPIKeyError when no key is configured."""
        client = USPTOClient(api_key=None)
        # Ensure environment key is not picked up
        client.api_key = None

        with self.assertRaises(USPTOMissingAPIKeyError) as ctx:
            client.search("solid state battery")

        self.assertIn("USPTO API key is required", str(ctx.exception))

    def test_empty_query_returns_empty_list_safely(self):
        """Verify search with blank query returns empty list without calling network."""
        client = USPTOClient(api_key="mock_key")
        self.assertEqual(client.search(""), [])
        self.assertEqual(client.search("   "), [])

    def test_public_search_contract_with_mocked_response(self):
        """Verify the public search() contract returns a list of raw dicts."""
        client = USPTOClient(api_key="mock_key")

        mock_payload = {
            "results": [
                {
                    "patentNumber": "US11456789B2",
                    "patentTitle": "High Energy Density Anode",
                    "abstractText": "An improved anode structure.",
                },
                {
                    "patentNumber": "US11456790B2",
                    "patentTitle": "Solid State Electrolyte",
                    "abstractText": "Electrolyte composition.",
                },
            ]
        }

        with mock.patch.object(client, "_send_request", return_value=mock_payload["results"]) as mock_send:
            results = client.search("battery", max_results=5)

            self.assertIsInstance(results, list)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["patentNumber"], "US11456789B2")
            mock_send.assert_called_once_with(
                endpoint="/search",
                params={"query": "battery", "limit": 5},
            )

    def test_http_error_converted_to_controlled_client_error(self):
        """Verify HTTP 401/403/500 errors are caught and converted to USPTOHTTPError."""
        client = USPTOClient(api_key="mock_key")

        mock_http_err = urllib.error.HTTPError(
            url="https://api.uspto.gov/api/v1/search",
            code=401,
            msg="Unauthorized",
            hdrs={},  # type: ignore
            fp=None,  # type: ignore
        )

        with mock.patch("urllib.request.urlopen", side_effect=mock_http_err):
            with self.assertRaises(USPTOHTTPError) as ctx:
                client.search("battery")

            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIsInstance(ctx.exception, USPTOClientError)

    def test_network_and_timeout_error_converted_to_controlled_error(self):
        """Verify URLError / TimeoutError are converted to USPTONetworkError."""
        client = USPTOClient(api_key="mock_key")

        # Test URLError
        mock_url_err = urllib.error.URLError("Connection refused")
        with mock.patch("urllib.request.urlopen", side_effect=mock_url_err):
            with self.assertRaises(USPTONetworkError):
                client.search("battery")

        # Test TimeoutError
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
            with self.assertRaises(USPTONetworkError):
                client.search("battery")

    def test_malformed_json_converted_to_response_error(self):
        """Verify malformed JSON responses raise USPTOResponseError."""
        client = USPTOClient(api_key="mock_key")

        mock_response = mock.MagicMock()
        mock_response.read.return_value = b"<html>Not JSON</html>"
        mock_response.__enter__.return_value = mock_response

        with mock.patch("urllib.request.urlopen", return_value=mock_response):
            with self.assertRaises(USPTOResponseError):
                client.search("battery")

    def test_client_does_not_access_sqlite(self):
        """Verify that constructing and using USPTOClient does not touch SQLite."""
        with mock.patch("sqlite3.connect") as mock_sqlite:
            client = USPTOClient(api_key="mock_key")
            with mock.patch.object(client, "_send_request", return_value=[{"id": "test"}]):
                client.search("battery")

            mock_sqlite.assert_not_called()


if __name__ == "__main__":
    unittest.main()
