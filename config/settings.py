"""Configuration settings for Patent -> Problem -> Startup Opportunity Research Engine."""

import os
from pathlib import Path
from typing import Optional

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"

# SQLite Database
DATABASE_PATH = Path(os.getenv("RESEARCH_ENGINE_DB_PATH", DATA_DIR / "research_engine.db"))

# USPTO Open Data Portal API Configuration
USPTO_DEFAULT_BASE_URL = "https://api.uspto.gov/api/v1"
USPTO_API_BASE_URL = os.getenv("USPTO_API_BASE_URL", USPTO_DEFAULT_BASE_URL)
USPTO_API_KEY = os.getenv("USPTO_API_KEY")


def get_uspto_config() -> dict[str, Optional[str]]:
    """Retrieve current USPTO configuration dynamically from environment."""
    return {
        "api_key": os.getenv("USPTO_API_KEY"),
        "base_url": os.getenv("USPTO_API_BASE_URL", USPTO_DEFAULT_BASE_URL),
    }


# EPO Open Patent Services (OPS) API Configuration
EPO_DEFAULT_BASE_URL = "https://ops.epo.org/3.2/rest-services"
EPO_DEFAULT_TOKEN_URL = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_API_BASE_URL = os.getenv("EPO_API_BASE_URL", EPO_DEFAULT_BASE_URL)
EPO_TOKEN_URL = os.getenv("EPO_TOKEN_URL", EPO_DEFAULT_TOKEN_URL)
EPO_CONSUMER_KEY = os.getenv("EPO_CONSUMER_KEY")
EPO_CONSUMER_SECRET = os.getenv("EPO_CONSUMER_SECRET")


def get_epo_config() -> dict[str, Optional[str]]:
    """Retrieve current EPO configuration dynamically from environment."""
    return {
        "base_url": os.getenv("EPO_API_BASE_URL", EPO_DEFAULT_BASE_URL),
        "token_url": os.getenv("EPO_TOKEN_URL", EPO_DEFAULT_TOKEN_URL),
        "consumer_key": os.getenv("EPO_CONSUMER_KEY"),
        "consumer_secret": os.getenv("EPO_CONSUMER_SECRET"),
    }


# Tavily Search API Configuration
TAVILY_DEFAULT_API_URL = "https://api.tavily.com/search"
TAVILY_API_BASE_URL = os.getenv("TAVILY_API_BASE_URL", TAVILY_DEFAULT_API_URL)
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")


def get_tavily_config() -> dict[str, Optional[str]]:
    """Retrieve current Tavily configuration dynamically from environment."""
    return {
        "api_key": os.getenv("TAVILY_API_KEY"),
        "base_url": os.getenv("TAVILY_API_BASE_URL", TAVILY_DEFAULT_API_URL),
    }

