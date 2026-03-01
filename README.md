# FIONAA — FInancial ONline loan Application Assistant

![FIONAA Logo](logo.png)

FIONAA is an AI-powered business loan application assessment pipeline. It uses a multi-agent  architecture to automatically evaluate loan applications by assessing eligibility, analysing financial data, and researching applicants via external sources to reduce the amound of leg-work required by human assessors. Results are surfaced through an interactive UI with a chatbot that allows the assessor to ask questions of the documents or make changes.

---

## Purpose

Given a loan application and supporting documents, FIONAA:

1. Extracts and structures document content using OCR (Landing AI ADE)
2. Runs a set of specialist sub-agents in parallel across the application
3. Persists structured findings to a PostgreSQL memory store
4. Provides a Streamlit interface for browsing documents, reading findings, and asking follow-up questions

---

## Technology Stack

| Layer | Technology |
|---|---|
| Agent orchestration | [LangGraph](https://langchain-ai.github.io/langgraph/) + [DeepAgents](https://pypi.org/project/deepagents/) |
| LLM | Anthropic Claude (Sonnet 4.5, Haiku 4.5) |
| OCR / Document intelligence | [Landing AI ADE](https://landing.ai/) |
| Vector embeddings | OpenAI `text-embedding-3-small` via `PGVectorStore` |
| Persistent memory | PostgreSQL (`AsyncPostgresStore`) |
| External data sources | LinkedIn MCP, Companies House MCP, Tavily web search |
| UI | Streamlit |
| Package manager | [uv](https://github.com/astral-sh/uv) |

---

## Project Structure

```
fionaa-be/
├── app.py                          # Streamlit UI
├── src/
│   ├── graph.py                    # Main LangGraph graph definition
│   ├── agents.py                   # Standalone agent factories (for testing)
│   ├── subagents.py                # Sub-agent configuration dicts
│   ├── chatbot_graph.py            # Case Q&A chatbot graph
│   ├── config.py                   # Paths and database configuration
│   ├── main.py                     # CLI entry point
│   ├── ocr_extraction.py           # Landing AI ADE OCR pipeline
│   ├── vector_store.py             # PGVectorStore initialisation
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
│   ├── workspace/
│   │   ├── loan_policy_documents/  # Policy documents read by agents
│   │   └── ocr_output/             # OCR extractions, organised by case
│   └── <case_name>/                # Source documents per case
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
  ├─ Init PostgreSQL checkpointer & store
  ├─ Connect LinkedIn & Companies House MCP servers
  └─ Compile StateGraph
       │
       ├──[OCR enabled]──► startup_node
       │                   ├─ Read docs from data/<case>/
       │                   ├─ Landing AI ADE: parse → classify → extract
       │                   ├─ Persist JSON + PNG to workspace/ocr_output/<case>/
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
  Findings saved to PostgreSQL /memories/<case>/
  └─ report.md  (final assessment summary)
       │
       ▼
  Streamlit UI  (app.py)
  ├─ Browse OCR output and memory records
  └─ Chatbot: RAG over findings + PGVectorStore
```

### Backend Routing

A `CompositeBackend` in `graph.py` routes agent file paths to the correct store:

| Path prefix | Backend | Storage |
|---|---|---|
| `/memories/` | `StoreBackend` | PostgreSQL (persistent, case-scoped) |
| `/disk-files/` | `FilesystemBackend` | `data/workspace/` (read/write) |
| everything else | `StateBackend` | In-memory (ephemeral) |

---

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- PostgreSQL running locally on port 5432 with a database named `langchain`
- pgvector extension enabled in PostgreSQL

### Install dependencies

```bash
uv sync
```

### Environment variables

Create a `.env` file in the project root: see .env.sample


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

Opens at `http://localhost:8501`. The sidebar lists cases organised into **supporting docs** (OCR output files) and **reports** (agent findings). The **Chat** tab provides Q&A interface over said docs.

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

then run the email pipline to trigger email ingest (or schedule with cron)

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



**Case isolation** — All data (memory records, OCR extractions, embeddings) is keyed by `case_number`, enabling separate loan applications without interference.


**MCPs for external data** — LinkedIn and Companies House are accessed via MCP servers rather than direct API clients,

**Security** — The `read_external_file` filesystem tool enforces a permission check that restricts agent access to the workspace directory only.

**Agentic RAG*** - for Q & A for a deeper dive into the longer documents like annual reports (10Ks) that can be tens or hundreds of pages long, and also ability to provide feedback to request changes to the documents.

**Memory** Postgres persistance of a Vectorstore for RAG, and Agent memories, such as the reports generated.