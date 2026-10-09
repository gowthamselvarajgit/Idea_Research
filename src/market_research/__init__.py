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
from src.market_research.duckduckgo_provider import (
    DuckDuckGoHTMLSearchProvider,
    DuckDuckGoHTTPError,
    DuckDuckGoNetworkError,
    DuckDuckGoSearchError,
    DuckDuckGoTimeoutError,
)
from src.market_research.fallback_search_provider import (
    AllProvidersFailedError,
    FallbackSearchProvider,
    FallbackSearchProviderError,
    create_default_search_provider,
)
from src.market_research.tavily_provider import (
    TavilyAuthenticationError,
    TavilyHTTPError,
    TavilyNetworkError,
    TavilyRateLimitError,
    TavilySearchError,
    TavilySearchProvider,
    TavilyTimeoutError,
)
from src.market_research.research_prompt import (
    MARKET_RESEARCH_SYSTEM_PROMPT,
    format_market_research_user_prompt,
)
from src.market_research.research_query_generator import (
    DEFAULT_RESEARCH_CATEGORIES,
    GeneratedResearchQueries,
    ResearchQueryGenerator,
    ResearchQueryItem,
    generate_research_queries,
)
from src.market_research.search_client import (
    SearchClient,
    SearchClientError,
    SearchProvider,
    SearchProviderError,
    SearchQueryValidationError,
    search,
)
from src.market_research.search_contract import (
    REQUIRED_SEARCH_RESULT_FIELDS,
    SearchResultContractValidationError,
    validate_search_result_contract,
    validate_search_result_payload,
    validate_search_result_record,
)
from src.market_research.search_models import (
    SearchResult,
)
from src.market_research.search_source_collector import (
    SearchSourceCollectionResult,
    SearchSourceCollector,
    SearchSourceCollectorError,
    collect_sources_for_search_query,
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
from src.market_research.web_evidence_analyzer import (
    InvalidOpportunityIdError,
    WebEvidenceAnalyzer,
    WebEvidenceAnalyzerError,
    analyze_web_sources,
    format_web_source_evidence,
    format_web_sources_evidence,
)


__all__ = [
    "ALLOWED_RELEVANCE",
    "ALLOWED_SOURCE_TYPES",
    "AllProvidersFailedError",
    "create_default_search_provider",
    "DEFAULT_RESEARCH_CATEGORIES",
    "DuckDuckGoHTMLSearchProvider",
    "DuckDuckGoHTTPError",
    "DuckDuckGoNetworkError",
    "DuckDuckGoSearchError",
    "DuckDuckGoTimeoutError",
    "FallbackSearchProvider",
    "FallbackSearchProviderError",
    "GeneratedResearchQueries",
    "InvalidOpportunityError",
    "InvalidOpportunityIdError",
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
    "REQUIRED_SEARCH_RESULT_FIELDS",
    "REQUIRED_SOURCE_FIELDS",
    "ResearchQueryGenerator",
    "ResearchQueryItem",
    "SearchClient",
    "SearchClientError",
    "SearchProvider",
    "SearchProviderError",
    "SearchQueryValidationError",
    "SearchResult",
    "SearchResultContractValidationError",
    "SearchSourceCollectionResult",
    "SearchSourceCollector",
    "SearchSourceCollectorError",
    "SourceCollectionFailure",
    "SourceCollectionResult",
    "TavilyAuthenticationError",
    "TavilyHTTPError",
    "TavilyNetworkError",
    "TavilyRateLimitError",
    "TavilySearchError",
    "TavilySearchProvider",
    "TavilyTimeoutError",
    "WebEvidenceAnalyzer",
    "WebEvidenceAnalyzerError",
    "WebResearchSource",
    "WebResearchSourceContractValidationError",
    "WebSourceClient",
    "WebSourceClientError",
    "WebSourceCollector",
    "WebSourceContentError",
    "WebSourceHTTPError",
    "WebSourceInvalidURLError",
    "WebSourceNetworkError",
    "analyze_web_sources",
    "collect_sources",
    "collect_sources_for_search_query",
    "fetch_source",
    "format_market_research_user_prompt",
    "format_web_source_evidence",
    "format_web_sources_evidence",
    "generate_research_queries",

    "parse_market_research_output",
    "search",
    "validate_market_research_contract",
    "validate_market_research_payload",
    "validate_market_research_record",
    "validate_search_result_contract",
    "validate_search_result_payload",
    "validate_search_result_record",
    "validate_web_research_source_contract",
    "validate_web_research_source_payload",
    "validate_web_research_source_record",
]
