"""Market Research domain module.

Provides data structures, schemas, and contract rules for structured market evidence,
competitive intelligence, and finding verification connected to startup opportunities.
"""

from src.market_research.contract import (
    ALLOWED_RELEVANCE,
    MARKET_RESEARCH_CONTRACT_PRINCIPLES,
    REQUIRED_MARKET_RESEARCH_FIELDS,
    MarketResearchContractValidationError,
    validate_market_research_contract,
    validate_market_research_payload,
    validate_market_research_record,
)
from src.market_research.models import (
    MarketResearchRecord,
)
from src.market_research.output_parser import (
    MarketResearchOutputParseError,
    OpportunityIdMismatchError,
    parse_market_research_output,
)
from src.market_research.repository import (
    MarketResearchNotFoundError,
    MarketResearchRepository,
    MarketResearchRepositoryError,
    OpportunityNotFoundError,
)
from src.market_research.research_prompt import (
    MARKET_RESEARCH_SYSTEM_PROMPT,
    format_market_research_user_prompt,
)
from src.market_research.service import (
    InvalidOpportunityError,
    MarketResearchAIError,
    MarketResearchParseError,
    MarketResearchPersistenceError,
    MarketResearchService,
    MarketResearchServiceError,
)
from src.market_research.source_collection import (
    SourceCollectionFailure,
    SourceCollectionResult,
    WebSourceCollector,
    collect_sources,
)
from src.market_research.source_contract import (
    REQUIRED_SOURCE_FIELDS,
    WebResearchSourceContractValidationError,
    validate_web_research_source_contract,
    validate_web_research_source_payload,
    validate_web_research_source_record,
)
from src.market_research.source_models import (
    ALLOWED_SOURCE_TYPES,
    WebResearchSource,
)
from src.market_research.web_source_client import (
    WebSourceClient,
    WebSourceClientError,
    WebSourceContentError,
    WebSourceHTTPError,
    WebSourceInvalidURLError,
    WebSourceNetworkError,
    fetch_source,
)

__all__ = [
    "ALLOWED_RELEVANCE",
    "ALLOWED_SOURCE_TYPES",
    "InvalidOpportunityError",
    "MARKET_RESEARCH_CONTRACT_PRINCIPLES",
    "MARKET_RESEARCH_SYSTEM_PROMPT",
    "MarketResearchAIError",
    "MarketResearchContractValidationError",
    "MarketResearchNotFoundError",
    "MarketResearchOutputParseError",
    "MarketResearchParseError",
    "MarketResearchPersistenceError",
    "MarketResearchRecord",
    "MarketResearchRepository",
    "MarketResearchRepositoryError",
    "MarketResearchService",
    "MarketResearchServiceError",
    "OpportunityIdMismatchError",
    "OpportunityNotFoundError",
    "REQUIRED_MARKET_RESEARCH_FIELDS",
    "REQUIRED_SOURCE_FIELDS",
    "SourceCollectionFailure",
    "SourceCollectionResult",
    "WebResearchSource",
    "WebResearchSourceContractValidationError",
    "WebSourceClient",
    "WebSourceClientError",
    "WebSourceCollector",
    "WebSourceContentError",
    "WebSourceHTTPError",
    "WebSourceInvalidURLError",
    "WebSourceNetworkError",
    "collect_sources",
    "fetch_source",
    "format_market_research_user_prompt",
    "parse_market_research_output",
    "validate_market_research_contract",
    "validate_market_research_payload",
    "validate_market_research_record",
    "validate_web_research_source_contract",
    "validate_web_research_source_payload",
    "validate_web_research_source_record",
]
