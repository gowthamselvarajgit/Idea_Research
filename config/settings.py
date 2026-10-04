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
