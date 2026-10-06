# Market Research Search Provider Options

## 1. Executive Summary & Context

To power the Market Research domain's competitive discovery workflow, the engine requires a concrete search discovery provider that satisfies the newly implemented `SearchProvider` protocol:

```python
class SearchProvider(Protocol):
    def search(self, query: str, max_results: int) -> Sequence[SearchResult]:
        ...
```

Per architectural requirements, the search capability must:
1. Be **completely free** (zero API subscription or search billing costs).
2. Require **no paid API keys** or proprietary third-party subscriptions.
3. Be fully executable using existing Python runtime packages (or standard library networking).
4. Run safely without headless browser automation, Selenium, or CAPTCHA solving.
5. Return authentic public HTTP/HTTPS URLs with titles, snippets, and domains.

---

## 2. What Was Inspected

The following environment components were rigorously inspected and verified on the host system:

### A. Python Environment & Installed Packages
- Inspected installed packages via `pip list` in Python 3.13:
  - **Standard library networking**: `urllib.request`, `urllib.parse`, `urllib.error`, `html.parser` are available.
  - **HTTP libraries present**: `requests` (2.34.2), `httpx` (0.28.1), `urllib3` (2.8.0).
  - **HTML/parsing libraries present**: `html.parser` (standard library).
  - **Search packages NOT installed**: `duckduckgo_search` / `ddgs`, `googlesearch-python`, `serpapi`, and `tavily-python` are **not installed**.

### B. Project Configuration & Environment Variables
- Inspected `config/settings.py` and active OS environment variables:
  - Configured APIs in `settings.py`: Only USPTO (`USPTO_API_KEY`, `USPTO_API_BASE_URL`) and EPO (`EPO_CONSUMER_KEY`, `EPO_CONSUMER_SECRET`, `EPO_DEFAULT_BASE_URL`).
  - Search engine API keys: **Zero keys configured** (`GOOGLE_API_KEY`, `BING_SEARCH_API_KEY`, `SERPAPI_API_KEY`, `TAVILY_API_KEY` are all unset).
  - Runtime environment variables: Only standard paths and `ANTIGRAVITY_AGENTAPI_EXE` (language server) are active.

### C. Antigravity Runtime & CLI Capabilities
- Inspected `agy` executable (`agy --help`, `agy models`):
  - `agy` exposes the Gemini models (`gemini-3.8-flash-low`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-high`) through subprocess calls for LLM reasoning and extraction.
  - `agy` does **not** expose a dedicated standalone web-search CLI command for programmatic subprocess invocation.
  - While the Antigravity IDE agent has internal MCP/IDE web tools, they are not exposed as a standard Python API to application runtime code.

### D. Public Web Search Endpoints (Live Verification)
- Tested direct standard-library HTTP requests against public search endpoints without credentials:
  - **DuckDuckGo HTML Endpoint (`https://html.duckduckgo.com/html/`)**: Verified active and responsive via standard `urllib.request` POST requests. Returns server-side rendered HTML containing real search URLs, titles, and snippets with no authentication or API keys required.
  - **DuckDuckGo Lite Endpoint (`https://lite.duckduckgo.com/lite/`)**: Verified active and responsive. Returns simplified HTML with search links and snippets.

---

## 3. Evaluation of Candidate Search Capabilities

### Option 1: DuckDuckGo HTML Endpoint (Direct Standard-Library POST)
- **Mechanism**: Issues HTTP POST requests to `https://html.duckduckgo.com/html/` with form-encoded `q={query}` and a standard browser `User-Agent`.
- **Cost**: **Completely Free** (100% free, zero cost, no account required).
- **Authentication**: **None** (no API key, no token, no credit card).
- **Dependencies**: Uses `urllib.request`, `urllib.parse`, and `html.parser` (zero external dependencies).
- **Data Returned**: Title, snippet, destination URL, and domain for each result.
- **Feasibility**: **Verified working in this environment**.

### Option 2: DuckDuckGo Lite Endpoint (`https://lite.duckduckgo.com/lite/`)
- **Mechanism**: Issues HTTP POST/GET to DuckDuckGo's ultra-lightweight accessibility endpoint.
- **Cost**: **Completely Free**.
- **Authentication**: **None**.
- **Dependencies**: Standard library only.
- **Data Returned**: Clean numbered search links and brief description text.
- **Feasibility**: Verified working; slightly less detailed snippets compared to the HTML endpoint.

### Option 3: Wikipedia OpenSearch API (`https://en.wikipedia.org/w/api.php`)
- **Mechanism**: Public REST endpoint returning structured JSON containing article titles, snippets, and URLs.
- **Cost**: **Completely Free**.
- **Authentication**: **None**.
- **Dependencies**: Standard library `urllib`.
- **Limitation**: Only searches Wikipedia articles. Does not discover private competitors, company landing pages, product docs, or pricing pages.

### Option 4: Commercial Search APIs (Google Custom Search, Bing Web Search, SerpAPI, Tavily, Brave)
- **Mechanism**: Dedicated JSON search APIs.
- **Cost**: **Requires payment / paid subscription** after tiny trial tiers.
- **Authentication**: **Requires active API keys and account registration**.
- **Limitation**: Not configured in the environment; incompatible with the strict "must NOT pay for APIs" constraint.

---

## 4. Free vs. Paid Comparison Table

| Candidate Provider | Free? | API Key Required? | External Lib Needed? | Commercial / General Web Scope? | Verified in Environment? |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **DuckDuckGo HTML Endpoint** | **Yes (100%)** | **No** | **No (Standard Lib)** | **Yes (Full Web)** | **Yes (Verified)** |
| **DuckDuckGo Lite Endpoint** | **Yes (100%)** | **No** | **No (Standard Lib)** | **Yes (Full Web)** | **Yes (Verified)** |
| **Wikipedia OpenSearch API** | Yes (100%) | No | No (Standard Lib) | No (Wikipedia only) | Yes |
| **Google Custom Search API** | Free tier (100/day) | **Yes** | No | Yes | No (Key missing) |
| **Bing Web Search API** | Paid / Trial | **Yes** | No | Yes | No (Key missing) |
| **SerpAPI** | Paid / 100/mo trial | **Yes** | No | Yes | No (Key missing) |
| **Tavily / Brave Search** | Paid / Trial | **Yes** | No | Yes | No (Key missing) |

---

## 5. Technical Compatibility with `SearchProvider` Interface

The project defines:

```python
@runtime_checkable
class SearchProvider(Protocol):
    def search(self, query: str, max_results: int) -> Sequence[SearchResult]:
        ...
```

A DuckDuckGo HTML-based provider maps directly to this contract:
1. Accepts `query: str` and `max_results: int`.
2. Formats and sends an HTTP POST to `https://html.duckduckgo.com/html/` using `urllib.request`.
3. Parses HTML elements (`.result__title`, `.result__snippet`, `.result__url`) with `html.parser.HTMLParser`.
4. Extracts clean `url`, `title`, `snippet`, and derives `domain = urlparse(url).netloc`.
5. Instantiates and returns validated immutable `SearchResult` records.
6. Caps results at `max_results` (bounded between 1 and 100).

---

## 6. Recommended Next Provider to Implement

### Recommendation: `DuckDuckGoHTMLSearchProvider` (Standard Library Implementation)

**Why this is the optimal choice:**
1. **Completely Free**: No monthly fees, no pay-per-search costs, no billing accounts.
2. **Zero API Key Overhead**: Works immediately in any environment without onboarding or secrets management.
3. **Zero New Dependencies**: Implemented cleanly using Python's standard library (`urllib.request`, `urllib.parse`, and `html.parser`).
4. **General Web Coverage**: Discovers actual competitors, software products, news articles, and vendor websites.
5. **Direct Contract Compatibility**: Produces structured `SearchResult` records conforming to `SearchProvider`.

---

## 7. Known Limitations, Rate Limits & Mitigation Strategies

1. **Rate Limiting / Throttling**:
   - DuckDuckGo may temporarily rate-limit an IP or return a bot challenge if queries are sent too frequently.
   - *Mitigation*:
     - Add conservative inter-request delays (e.g. 1.0–2.0 seconds) if performing multiple searches.
     - Use a realistic, descriptive `User-Agent`.
     - Deduplicate queries before making network requests.
2. **Redirect URLs**:
   - DuckDuckGo results occasionally wrap destination links in internal tracking redirects (e.g., `//duckduckgo.com/l/?uddg=https%3A%2F%2F...`).
   - *Mitigation*: Decode the `uddg` query parameter to extract the true target destination URL directly.
3. **No Heavy Pagination**:
   - Best suited for top 10–30 discovery results per query (which matches our target `max_results=10`).
