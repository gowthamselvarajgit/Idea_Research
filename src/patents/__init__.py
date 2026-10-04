from src.patents.base_client import BasePatentClient, PatentClientError
from src.patents.epo_auth import (
    EPOAuthClient,
    EPOAuthError,
    EPOHTTPError,
    EPOMissingCredentialsError,
    EPONetworkError,
    EPOResponseError,
)
from src.patents.epo_client import (
    EPOClient,
    EPOClientAuthenticationError,
    EPOClientError,
    EPOClientHTTPError,
    EPOClientNetworkError,
    EPOClientResponseError,
)
from src.patents.discovery_service import (
    DiscoveryStats,
    EPODiscoveryError,
    EPODiscoveryService,
)
from src.patents.epo_parser import EPOParserError, parse_epo_search_response
from src.patents.models import (
    PatentRecord,
    build_canonical_url,
    is_valid_patent_number,
    normalize_patent_components,
    normalize_patent_number,
    validate_patent_number,
)

from src.patents.uspto_client import (
    USPTOClient,
    USPTOClientError,
    USPTOHTTPError,
    USPTOMissingAPIKeyError,
    USPTONetworkError,
    USPTOResponseError,
)

__all__ = [
    "BasePatentClient",
    "DiscoveryStats",
    "EPOAuthClient",
    "EPOAuthError",
    "EPOClient",
    "EPOClientAuthenticationError",
    "EPOClientError",
    "EPOClientHTTPError",
    "EPOClientNetworkError",
    "EPOClientResponseError",
    "EPODiscoveryError",
    "EPODiscoveryService",
    "EPOHTTPError",
    "EPOMissingCredentialsError",
    "EPONetworkError",
    "EPOParserError",
    "EPOResponseError",
    "PatentClientError",
    "PatentRecord",
    "USPTOClient",
    "USPTOClientError",
    "USPTOHTTPError",
    "USPTOMissingAPIKeyError",
    "USPTONetworkError",
    "USPTOResponseError",
    "build_canonical_url",
    "is_valid_patent_number",
    "normalize_patent_components",
    "normalize_patent_number",
    "parse_epo_search_response",
    "validate_patent_number",
]


