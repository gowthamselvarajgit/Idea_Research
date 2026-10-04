# Patent → Problem → Startup Opportunity Research Engine

A modular system to analyze patent corpora, extract core technical bottlenecks and underlying problems, and translate them into validated startup opportunities.

## Project Structure

```text
Startup_Research_Agent/
├── config/
│   ├── __init__.py
│   └── settings.py          # Configuration and settings loader
├── data/
│   ├── raw/                 # Ingested patent documents and raw records
│   ├── processed/           # Extracted problems and structured findings
│   └── reports/             # Generated research briefs and opportunity reports
├── src/
│   ├── __init__.py
│   ├── patents/             # Patent search, retrieval, and parsing
│   ├── problems/            # Technical problem and bottleneck extraction
│   ├── opportunities/       # Startup opportunity synthesis and commercialization
│   ├── evaluation/          # Viability, defensibility, and market scoring
│   ├── reporting/           # Report generation and export formatting
│   └── common/              # Shared data schemas, models, and utilities
├── tests/                   # Automated test suite
├── .env.example             # Template for environment configuration
├── .gitignore               # Standard ignore patterns
├── pyproject.toml           # Project packaging and metadata
└── README.md                # Project documentation
```

## Pipeline Architecture

1. **Patents (`src/patents/`)**: Ingestion and parsing of patent literature.
2. **Problems (`src/problems/`)**: Identification of latent technical friction, inefficiencies, and unmet needs.
3. **Opportunities (`src/opportunities/`)**: Mapping solved and unsolved problems to venture-scale market opportunities.
4. **Evaluation (`src/evaluation/`)**: Defensibility, market size, and execution feasibility scoring.
5. **Reporting (`src/reporting/`)**: Synthesis of findings into structured founder/investor research briefs.
