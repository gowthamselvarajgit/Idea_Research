"""EPO Open Patent Services (OPS) search client implementation.

Provides authenticated CQL-based bibliographic and abstract search against the
EPO OPS API, isolating endpoint routing and Range pagination.
"""

from typing import Any, Optional
import urllib.error
import urllib.parse
import urllib.request

from config.settings import EPO_API_BASE_URL
from src.patents.base_client import BasePatentClient, PatentClientError
from src.patents.epo_auth import EPOAuthClient, EPOAuthError


class EPOClientError(PatentClientError):
    """Base exception for all EPO search client errors."""
    pass


class EPOClientAuthenticationError(EPOClientError):
    """Raised when authentication with EPO OPS fails or token is rejected."""
    pass


class EPOClientNetworkError(EPOClientError):
    """Raised when a network failure, socket error, or timeout occurs."""
    pass


class EPOClientHTTPError(EPOClientError):
    """Raised when the EPO search API returns a non-2xx HTTP status code."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class EPOClientResponseError(EPOClientError):
    """Raised when the response from EPO OPS is malformed or invalid."""
    pass


class EPOClient(BasePatentClient):
    """Client for performing CQL searches on the EPO Open Patent Services (OPS) API."""

    MAX_PAGE_SIZE = 100
    DEFAULT_ENDPOINT_PATH = "/published-data/search/abstract,biblio"

    def __init__(
        self,
        auth_client: Optional[EPOAuthClient] = None,
        base_url: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the EPO OPS search client.

        Args:
            auth_client: EPOAuthClient instance for token management.
            base_url: Base endpoint URL. Defaults to config.settings.EPO_API_BASE_URL.
            endpoint_path: Relative path for search. Defaults to /published-data/search/abstract,biblio.
            timeout: Network request timeout in seconds.
        """
        self.auth_client = auth_client or EPOAuthClient()
        self.base_url = (base_url or EPO_API_BASE_URL).rstrip("/")
        self.endpoint_path = endpoint_path or self.DEFAULT_ENDPOINT_PATH
        self.timeout = timeout

    def search(
        self,
        query: str,
        max_results: int = 10,
        start_index: int = 1,
    ) -> str:
        """Execute a CQL search query against EPO OPS.

        Args:
            query: CQL query string (e.g. 'ta="solid state battery" AND ta="dendrite"').
            max_results: Maximum number of records to retrieve (safe maximum: 100).
            start_index: 1-indexed start position (default: 1).

        Returns:
            str: Raw search response payload (typically XML).

        Raises:
            EPOClientAuthenticationError: On token retrieval or auth failure.
            EPOClientNetworkError: On socket or timeout failure.
            EPOClientHTTPError: On non-2xx HTTP response status.
            EPOClientResponseError: On empty or malformed response payload.
        """
        if not query or not query.strip():
            return ""

        # Enforce safe bounds on Range pagination
        start = max(1, start_index)
        count = max(1, min(max_results, self.MAX_PAGE_SIZE))
        end = start + count - 1
        range_str = f"{start}-{end}"

        # 1. Obtain access token
        try:
            token = self.auth_client.get_access_token()
        except EPOAuthError as err:
            raise EPOClientAuthenticationError(f"EPO authentication failed: {err}") from err

        # 2. Dispatch request
        params = {
            "q": query.strip(),
            "Range": range_str,
        }

        return self._send_request(
            endpoint=self.endpoint_path,
            params=params,
            range_header=range_str,
            token=token,
        )

    def _send_request(
        self,
        endpoint: str,
        params: dict[str, Any],
        range_header: str,
        token: str,
    ) -> str:
        """Internal helper to dispatch authenticated request to EPO OPS.

        Isolated to allow safe mocking and clean testing.
        """
        url = f"{self.base_url}{endpoint}"
        query_string = urllib.parse.urlencode(params)
        request_url = f"{url}?{query_string}" if params else url

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/xml",
            "X-OPS-Range": range_header,
            "User-Agent": "StartupResearchAgent/1.0",
        }

        req = urllib.request.Request(request_url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                raise EPOClientAuthenticationError(
                    f"EPO API request rejected with HTTP {err.code}: {err.reason}",
                ) from err
            raise EPOClientHTTPError(
                f"EPO API HTTP error {err.code}: {err.reason}",
                status_code=err.code,
            ) from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise EPOClientNetworkError(f"EPO API network failure: {err}") from err

        if not payload or not payload.strip():
            raise EPOClientResponseError("Received empty response body from EPO OPS.")

        return payload
