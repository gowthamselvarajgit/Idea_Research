"""Configuration settings for Patent -> Problem -> Startup Opportunity Research Engine."""

import os
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"

# SQLite Database
DATABASE_PATH = Path(os.getenv("RESEARCH_ENGINE_DB_PATH", DATA_DIR / "research_engine.db"))
