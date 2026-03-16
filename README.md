# FIONAA — FInancial ONline loan Application Assistant

![FIONAA Logo](logo.png)

FIONAA is an AI-powered business loan application assessment pipeline. It uses a multi-agent  architecture to automatically evaluate loan applications by assessing eligibility, analysing financial data, and researching applicants via external sources to reduce the amound of leg-work required by human assessors. Results are surfaced through an interactive UI with a chatbot that allows the assessor to ask questions of the documents or make changes.

---

## Purpose

Given a loan application and supporting documents, FIONAA:

1. Extracts and structures document content using OCR (Landing AI ADE)
2. Runs a set of specialist sub-agents in parallel across the application
3. Persists structured findings to a GCS-backed memory store
4. Provides a Streamlit interface for browsing documents, reading findings, and asking follow-up questions

---

## Technology Stack

| Layer | Technology |
|---|---|
| Agent orchestration | [LangGraph](https://langchain-ai.github.io/langgraph/) + [DeepAgents](https://pypi.org/project/deepagents/) |
| LLM | Anthropic Claude (Sonnet 4.5, Haiku 4.5) |
| OCR / Document intelligence | [Landing AI ADE](https://landing.ai/) |
| Vector embeddings | OpenAI `text-embedding-3-small` via `PGVectorStore` |
| Persistent memory & file storage | Google Cloud Storage (`GCSBackend`) |
| External data sources | LinkedIn MCP, Companies House MCP, Tavily web search |
| UI | Streamlit (deployed to GCP Cloud Run) |
| Package manager | [uv](https://github.com/astral-sh/uv) |
| Secrets management | GCP Secret Manager |

---

## Project Structure

```
fionaa-be/
├── app.py                          # Streamlit UI
├── deploy.sh                       # GCP Cloud Run build & deploy script
├── Dockerfile                      # Container image definition
├── src/
│   ├── graph.py                    # Main LangGraph graph definition
│   ├── agents.py                   # Standalone agent factories (for testing)
│   ├── subagents.py                # Sub-agent configuration dicts
│   ├── chatbot_graph.py            # Case Q&A chatbot graph
│   ├── config.py                   # Paths and GCS prefix configuration
│   ├── main.py                     # CLI entry point
│   ├── ocr_extraction.py           # Landing AI ADE OCR pipeline
│   ├── vector_store.py             # PGVectorStore initialisation
│   ├── backends/
│   │   └── gcs_backend.py          # GCSBackend: read/write files in GCS
│   ├── prompts/
│   │   └── agent_prompts.py        # All agent prompt strings
│   ├── schemas/                    # Pydantic models
│   ├── tools/
│   │   ├── filesystem.py           # Read-only workspace file access
│   │   ├── internet_search.py      # Tavily web search tool
│   │   ├── linkedin.py             # LinkedIn MCP client
│   │   └── companies_house.py      # Companies House MCP client
│   └── gmail/                      # Gmail ingest pipeline
├── data/
│   └── <case_name>/                # Local staging: source documents per case
├── tests/
├── notebooks/
├── langgraph.json                  # LangGraph deployment config
└── pyproject.toml
```

---

## Architecture & Data Flow

```
Email / CLI ingest
       │
       ▼
  graph.build_graph()
  ├─ Setup Google credentials (GOOGLE_CREDENTIALS_JSON / ADC)
  ├─ Connect LinkedIn & Companies House MCP servers
  └─ Compile StateGraph
       │
       ├──[OCR enabled]──► startup_node
       │                   ├─ Read docs from data/<case>/ OR GCS <case>/loan_application/
       │                   ├─ Landing AI ADE: parse → classify → extract
       │                   ├─ Upload JSON + PNG to GCS <case>/ocr_output/
       │                   └─ Embed chunks → PGVectorStore
       │
       ▼
  assessment_deepagent  (DeepAgent orchestrator)
  ├─ eligibility-assessment-agent     → eligibility_findings.md
  ├─ financial-assessment-agent       → financial_assessment_findings.md
  ├─ linkedin-search-agent            → linkedin_findings.md
  ├─ companies-house-search-agent     → companies_house_findings.md
  └─ internet-search-agent            → internet_findings.md
       │
       ▼
  Findings saved to GCS <case>/reports/
  └─ report.md  (final assessment summary)
       │
       ▼
  Streamlit UI  (app.py — hosted on GCP Cloud Run)
  ├─ Browse OCR output and memory records (served from GCS)
  └─ Chatbot: RAG over findings + PGVectorStore
```

### Backend Routing

A `CompositeBackend` in `graph.py` routes agent file paths to the correct store:

| Path prefix | Backend | Storage |
|---|---|---|
| `/reports/` | `GCSBackend` | GCS `<case_number>/reports/` |
| `/disk-files/` | `GCSBackend` | GCS bucket root |
| everything else | `StateBackend` | In-memory (ephemeral) |

---

## GCP Infrastructure

The application is deployed to GCP under project `fionaa-483715` (region: `europe-west1`).

| Component | GCP Service | Details |
|---|---|---|
| Streamlit UI | Cloud Run | Service: `fionaa-app`, 2 CPU / 4 GiB RAM |
| Document & findings storage | Cloud Storage | Bucket: `fionaa-customer-assets` |
| API secrets | Secret Manager | One secret per API key (see below) |
| Container registry | Artifact Registry | `cloud-run-source-deploy` repo |
| MCP servers | Cloud Run | Companies House + LinkedIn MCP services |

### MCP Service URLs

| MCP Server | URL |
|---|---|
| Companies House | `https://companies-house-mcp-660196542212.europe-west1.run.app/` |
| LinkedIn | `https://linkedin-mcp-server-660196542212.europe-west1.run.app/` |

### GCS Bucket Layout

```
fionaa-customer-assets/
└── <case_number>/
    ├── loan_application/   # Original uploaded documents
    ├── ocr_output/         # Landing AI extraction JSON + annotated PNGs
    └── reports/            # Agent findings (*.md) and final report
```

### Deploying

Prerequisites:
- `gcloud` CLI authenticated (`gcloud auth login`)
- Application default credentials (`gcloud auth application-default login`)
- Project set (`gcloud config set project fionaa-483715`)

```bash
chmod +x deploy.sh
./deploy.sh
```

`deploy.sh` will:
1. Ensure the Artifact Registry repository exists
2. Create Secret Manager secrets from `.env` (idempotent — skips existing secrets)
3. Build the container image via Cloud Build
4. Deploy to Cloud Run with environment variables and secret bindings

---

## Local Setup

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- PostgreSQL running locally on port 5432 with a database named `langchain`
- pgvector extension enabled in PostgreSQL
- GCP credentials (either `GOOGLE_APPLICATION_CREDENTIALS` file path or `GOOGLE_CREDENTIALS_JSON` env var)

### Install dependencies

```bash
uv sync
```

### Environment variables

Create a `.env` file in the project root: see `.env.sample`

Key variables:

| Variable | Description |
|---|---|
| `BUCKET_NAME` | GCS bucket name (e.g. `fionaa-customer-assets`) |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `GOOGLE_CREDENTIALS_JSON` | Service account JSON (string) — for cloud deployments |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON file — for local use |
| `ANTHROPIC_API_KEY` | Claude API key |
| `OPENAI_API_KEY` | OpenAI API key (embeddings) |
| `LANGSMITH_API_KEY` | LangSmith tracing |
| `LANGGRAPH_URL` | LangGraph Cloud deployment URL |
| `TAVILY_API_KEY` | Tavily web search |
| `VISION_AGENT_API_KEY` | Landing AI ADE OCR key |

### Initialise the vector store table

```bash
uv run python src/vector_store.py
```

---

## Running the Application

### Streamlit UI

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. The sidebar lists cases organised into **supporting docs** (OCR output files) and **reports** (agent findings). The **Chat** tab provides a Q&A interface over said docs.

### Run an assessment via CLI

```bash
uv run python src/main.py --case <case_name> --application "<application text>"
```

Example:

```bash
uv run python src/main.py --case Synthesia --application "We are seeking a £500,000 loan..."
```

The `RUN_WITHOUT_OCR` and `RUN_WITHOUT_INTERNET_SEARCH` environment variables can be used to skip those pipeline stages during development.

### LangGraph Studio (local development)

```bash
langgraph dev
```

Opens LangGraph Studio at `http://localhost:2024`. Two graphs are exposed:

- `fionaa` — main assessment pipeline (`src/graph.py`)
- `chatbot` — case Q&A chatbot (`src/chatbot_graph.py`)

Then run the email pipeline to trigger email ingest (or schedule with cron):

```bash
uv run python src/gmail/ingest.py --email my.email@gmail.com --minutes-since 10
```

---

## Running Tests

```bash
pytest tests/
```

Tests use `pytest-asyncio` in auto mode. The `graph` fixture (session-scoped) builds the graph once for the entire test run.

---

## Key Design Decisions

**GCS as unified storage** — All file I/O (source documents, OCR output, agent findings) goes through the `GCSBackend`, which implements the `BackendProtocol` interface. This means the same agent code works both locally (via ADC) and in cloud deployments (via `GOOGLE_CREDENTIALS_JSON`).

**Case isolation** — All data (memory records, OCR extractions, embeddings) is keyed by `case_number`, enabling separate loan applications without interference.

**MCPs for external data** — LinkedIn and Companies House are accessed via MCP servers deployed to Cloud Run, rather than direct API clients.

**Security** — The `read_external_file` filesystem tool enforces a permission check that restricts agent access to the workspace directory only. Secrets are stored in GCP Secret Manager and injected at deploy time.

**Agentic RAG** — For Q&A, a deeper dive into longer documents like annual reports (10Ks) is supported via a RAG pipeline backed by `PGVectorStore`. Users can also provide feedback to request changes to documents.

**Memory** — Agent findings are persisted as Markdown files in GCS (`/reports/`), alongside a `PGVectorStore` for semantic search.
