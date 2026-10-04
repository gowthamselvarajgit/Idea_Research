"""EPO Open Patent Services (OPS) OAuth2 token authentication client.

Encapsulates the OAuth2 Client Credentials flow for EPO OPS using HTTP Basic
Authentication, conforming to the official EPO Developer specifications.
"""

import base64
import json
from typing import Optional
import urllib.error
import urllib.parse
import urllib.request

from config.settings import EPO_CONSUMER_KEY, EPO_CONSUMER_SECRET, EPO_TOKEN_URL
from src.patents.base_client import PatentClientError


class EPOAuthError(PatentClientError):
    """Base exception for all EPO authentication errors."""
    pass


class EPOMissingCredentialsError(EPOAuthError):
    """Raised when Consumer Key or Consumer Secret is not configured."""
    pass


class EPONetworkError(EPOAuthError):
    """Raised when a network failure or timeout occurs during authentication."""
    pass


class EPOHTTPError(EPOAuthError):
    """Raised when the EPO token endpoint returns an HTTP error status code."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class EPOResponseError(EPOAuthError):
    """Raised when the token response is malformed, not JSON, or missing access_token."""
    pass


class EPOAuthClient:
    """Client for acquiring OAuth2 access tokens from the EPO OPS token endpoint."""

    def __init__(
        self,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        token_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the EPO OAuth2 client.

        Args:
            consumer_key: EPO OPS Consumer Key. Defaults to config.settings.EPO_CONSUMER_KEY.
            consumer_secret: EPO OPS Consumer Secret. Defaults to config.settings.EPO_CONSUMER_SECRET.
            token_url: Token endpoint URL. Defaults to config.settings.EPO_TOKEN_URL.
            timeout: Request timeout in seconds.
        """
        self.consumer_key = consumer_key if consumer_key is not None else EPO_CONSUMER_KEY
        self.consumer_secret = consumer_secret if consumer_secret is not None else EPO_CONSUMER_SECRET
        self.token_url = token_url or EPO_TOKEN_URL
        self.timeout = timeout

    def get_access_token(self) -> str:
        """Request and return an OAuth2 Bearer access token from EPO OPS.

        Returns:
            str: Valid OAuth2 access token.

        Raises:
            EPOMissingCredentialsError: If consumer key or secret is missing.
            EPONetworkError: On connection/socket/timeout errors.
            EPOHTTPError: On non-2xx HTTP responses.
            EPOResponseError: On malformed or missing token payload.
        """
        if not self.consumer_key or not self.consumer_key.strip():
            raise EPOMissingCredentialsError(
                "EPO Consumer Key is missing. Set the EPO_CONSUMER_KEY environment variable "
                "or pass consumer_key to EPOAuthClient."
            )

        if not self.consumer_secret or not self.consumer_secret.strip():
            raise EPOMissingCredentialsError(
                "EPO Consumer Secret is missing. Set the EPO_CONSUMER_SECRET environment variable "
                "or pass consumer_secret to EPOAuthClient."
            )

        # Build HTTP Basic Authentication header: base64(key:secret)
        raw_credentials = f"{self.consumer_key}:{self.consumer_secret}".encode("utf-8")
        encoded_credentials = base64.b64encode(raw_credentials).decode("utf-8")

        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "StartupResearchAgent/1.0",
        }

        # Request payload: grant_type=client_credentials
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
        req = urllib.request.Request(self.token_url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            raise EPOHTTPError(
                f"EPO token request failed with HTTP {err.code}: {err.reason}",
                status_code=err.code,
            ) from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise EPONetworkError(f"EPO authentication network connection failure: {err}") from err

        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, ValueError) as err:
            raise EPOResponseError(f"Malformed JSON response from EPO token endpoint: {err}") from err

        if not isinstance(parsed, dict):
            raise EPOResponseError(
                f"Unexpected response type from EPO token endpoint. Expected dict, got {type(parsed).__name__}"
            )

        token = parsed.get("access_token")
        if not token or not isinstance(token, str):
            raise EPOResponseError(
                f"Missing or invalid 'access_token' in EPO token response: {parsed}"
            )

        return token
