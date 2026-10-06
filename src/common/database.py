"""SQLite database connection and schema management for the Research Engine.

Provides connection helpers, context managers, and schema initialization
designed to support storing research collected across multiple research runs.
"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Generator, Optional

from config.settings import DATABASE_PATH

# Foundational Schema DDL
SCHEMA_DDL = """
-- Research Runs: tracks distinct execution sessions and queries
CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    run_name TEXT NOT NULL,
    query TEXT,
    status TEXT NOT NULL DEFAULT 'initialized',
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Patents: stores canonical patent records (globally unique by patent_number)
CREATE TABLE IF NOT EXISTS patents (
    id TEXT PRIMARY KEY,
    patent_number TEXT NOT NULL UNIQUE,
    title TEXT,
    abstract TEXT,
    filing_date TEXT,
    publication_date TEXT,
    assignee TEXT,
    source_url TEXT,
    raw_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Run-Patents Junction: associates patents with the research runs that discovered/analyzed them
CREATE TABLE IF NOT EXISTS run_patents (
    run_id TEXT NOT NULL,
    patent_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, patent_id),
    FOREIGN KEY (run_id) REFERENCES research_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (patent_id) REFERENCES patents(id) ON DELETE CASCADE
);

-- Extracted Problems: stores technical problems and bottlenecks identified during a research run
CREATE TABLE IF NOT EXISTS extracted_problems (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    problem_title TEXT NOT NULL,
    problem_description TEXT,
    bottleneck_type TEXT,
    technical_domain TEXT,
    raw_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs(id) ON DELETE CASCADE
);

-- Problem-Patents Junction: allows a problem to be synthesized from multiple patents (M:N)
CREATE TABLE IF NOT EXISTS problem_patents (
    problem_id TEXT NOT NULL,
    patent_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (problem_id, patent_id),
    FOREIGN KEY (problem_id) REFERENCES extracted_problems(id) ON DELETE CASCADE,
    FOREIGN KEY (patent_id) REFERENCES patents(id) ON DELETE CASCADE
);

-- Startup Opportunities: stores venture opportunities synthesized during a research run
CREATE TABLE IF NOT EXISTS startup_opportunities (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    opportunity_title TEXT NOT NULL,
    solution_concept TEXT,
    target_customer TEXT,
    value_proposition TEXT,
    raw_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES research_runs(id) ON DELETE CASCADE
);

-- Opportunity-Problems Junction: allows an opportunity to reference multiple problems (M:N)
CREATE TABLE IF NOT EXISTS opportunity_problems (
    opportunity_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (opportunity_id, problem_id),
    FOREIGN KEY (opportunity_id) REFERENCES startup_opportunities(id) ON DELETE CASCADE,
    FOREIGN KEY (problem_id) REFERENCES extracted_problems(id) ON DELETE CASCADE
);

-- Opportunity Evaluations: stores multi-dimensional venture scoring and recommendations
CREATE TABLE IF NOT EXISTS opportunity_evaluations (
    id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    overall_score INTEGER NOT NULL,
    problem_severity_score INTEGER NOT NULL,
    frequency_score INTEGER NOT NULL,
    user_scale_score INTEGER NOT NULL,
    willingness_to_pay_score INTEGER NOT NULL,
    market_gap_score INTEGER NOT NULL,
    technology_leverage_score INTEGER NOT NULL,
    competition_score INTEGER NOT NULL,
    wow_factor_score INTEGER NOT NULL,
    recurring_potential_score INTEGER NOT NULL,
    social_impact_score INTEGER NOT NULL,
    execution_feasibility_score INTEGER NOT NULL,
    rejection_reasons TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    rationale TEXT NOT NULL,
    raw_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (opportunity_id) REFERENCES startup_opportunities(id) ON DELETE CASCADE
);

-- Market Research Findings: stores verified competitive intelligence and market evidence
CREATE TABLE IF NOT EXISTS market_research_findings (
    id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    company_or_product TEXT NOT NULL,
    finding TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    relevance TEXT NOT NULL,
    raw_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (opportunity_id) REFERENCES startup_opportunities(id) ON DELETE CASCADE
);

-- Indexes for efficient queries across runs, patents, problems, opportunities, evaluations, and market research
CREATE INDEX IF NOT EXISTS idx_patents_patent_number ON patents(patent_number);
CREATE INDEX IF NOT EXISTS idx_run_patents_run_id ON run_patents(run_id);
CREATE INDEX IF NOT EXISTS idx_run_patents_patent_id ON run_patents(patent_id);
CREATE INDEX IF NOT EXISTS idx_extracted_problems_run_id ON extracted_problems(run_id);
CREATE INDEX IF NOT EXISTS idx_problem_patents_problem_id ON problem_patents(problem_id);
CREATE INDEX IF NOT EXISTS idx_problem_patents_patent_id ON problem_patents(patent_id);
CREATE INDEX IF NOT EXISTS idx_startup_opportunities_run_id ON startup_opportunities(run_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_problems_opp_id ON opportunity_problems(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_problems_prob_id ON opportunity_problems(problem_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_evaluations_opp_id ON opportunity_evaluations(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_market_research_findings_opp_id ON market_research_findings(opportunity_id);
"""



def get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Create and configure a new SQLite database connection.

    Args:
        db_path: Path to SQLite database file. Defaults to config.settings.DATABASE_PATH.

    Returns:
        Configured sqlite3.Connection with Row factory, foreign keys, and WAL mode.
    """
    target_path = Path(db_path) if db_path else DATABASE_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


@contextmanager
def get_db(db_path: Optional[Path | str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for acquiring a database connection with auto-commit/rollback.

    Yields:
        sqlite3.Connection: Database connection.
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path | str] = None) -> Path:
    """Initialize the SQLite database file and execute the foundational schema.

    Args:
        db_path: Path to SQLite database file. Defaults to config.settings.DATABASE_PATH.

    Returns:
        Path to the initialized database file.
    """
    target_path = Path(db_path) if db_path else DATABASE_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with get_db(target_path) as conn:
        conn.executescript(SCHEMA_DDL)

    return target_path


if __name__ == "__main__":
    db_file = init_db()
    print(f"Database successfully initialized at: {db_file}")
