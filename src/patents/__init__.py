from src.patents.base_client import BasePatentClient, PatentClientError
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
    "validate_patent_number",
]

