"""USPTO Open Data Portal client implementation.

Encapsulates authentication, network communication, error handling, and search
dispatching for the USPTO API, conforming to BasePatentClient.
"""

import json
from typing import Any, Optional
import urllib.error
import urllib.parse
import urllib.request

from config.settings import USPTO_API_BASE_URL, USPTO_API_KEY
from src.patents.base_client import BasePatentClient, PatentClientError


class USPTOClientError(PatentClientError):
    """Base exception for all USPTO client errors."""
    pass


class USPTOMissingAPIKeyError(USPTOClientError):
    """Raised when an operation requires an API key but none is configured."""
    pass


class USPTONetworkError(USPTOClientError):
    """Raised when a network error, socket failure, or timeout occurs."""
    pass


class USPTOHTTPError(USPTOClientError):
    """Raised when the USPTO API returns an HTTP error status code."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class USPTOResponseError(USPTOClientError):
    """Raised when the response from USPTO is malformed or unparseable."""
    pass


class USPTOClient(BasePatentClient):
    """Client for querying the USPTO Open Data Portal API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the USPTO client.

        Args:
            api_key: USPTO Open Data Portal API key. Defaults to config.settings.USPTO_API_KEY.
            base_url: Base endpoint URL. Defaults to config.settings.USPTO_API_BASE_URL.
            timeout: HTTP request timeout in seconds.
        """
        self.api_key = api_key if api_key is not None else USPTO_API_KEY
        self.base_url = (base_url or USPTO_API_BASE_URL).rstrip("/")
        self.timeout = timeout

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Search the USPTO for candidate patents matching a query.

        Args:
            query: Domain topic or keyword search string.
            max_results: Maximum number of raw records to retrieve (default: 10).

        Returns:
            list[dict]: List of raw patent records from the USPTO response.

        Raises:
            USPTOMissingAPIKeyError: If no API key is configured.
            USPTONetworkError: If a connection or timeout failure occurs.
            USPTOHTTPError: If the server returns an HTTP error code.
            USPTOResponseError: If the server response is malformed.
        """
        if not query or not query.strip():
            return []

        if not self.api_key or not self.api_key.strip():
            raise USPTOMissingAPIKeyError(
                "USPTO API key is required to perform searches. "
                "Set the USPTO_API_KEY environment variable or pass api_key to USPTOClient."
            )

        bounded_limit = max(1, min(max_results, 100))
        params = {
            "query": query.strip(),
            "limit": bounded_limit,
        }

        return self._send_request(endpoint="/search", params=params)

    def _send_request(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Internal helper to dispatch HTTP request to USPTO API.

        Isolated to allow safe mocking and protect callers from network details.
        """
        url = f"{self.base_url}{endpoint}"
        query_string = urllib.parse.urlencode(params)
        request_url = f"{url}?{query_string}" if params else url

        headers = {
            "X-API-KEY": self.api_key or "",
            "Accept": "application/json",
            "User-Agent": "StartupResearchAgent/1.0",
        }

        req = urllib.request.Request(request_url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            raise USPTOHTTPError(
                f"USPTO API HTTP error {err.code}: {err.reason}",
                status_code=err.code,
            ) from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise USPTONetworkError(f"USPTO API network connection failure: {err}") from err

        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, ValueError) as err:
            raise USPTOResponseError(f"Malformed JSON response from USPTO API: {err}") from err

        if not isinstance(parsed, (dict, list)):
            raise USPTOResponseError(
                f"Unexpected response structure from USPTO API. Expected dict/list, got {type(parsed).__name__}"
            )

        # Handle typical result container shapes
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]

        # If wrapped under 'results', 'patents', or 'patentData'
        for key in ("results", "patents", "patentData", "data"):
            if key in parsed and isinstance(parsed[key], list):
                return [item for item in parsed[key] if isinstance(item, dict)]

        return [parsed]
