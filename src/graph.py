"""LangGraph orchestration for the Fionaa loan application assessment pipeline.

Graph topology
--------------
START → [conditional] → startup → assessment_deepagent → END
                └──────────────→ assessment_deepagent (when config run_without_ocr=True)

* ``startup``              — runs OCR on every document attached to the case and
                             persists structured extractions to the workspace.
* ``assessment_deepagent`` — deep-research orchestrator that delegates to
                             specialist sub-agents (eligibility, financial,
                             LinkedIn, Companies House, internet search) and
                             produces a final report saved in agent memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import List

from deepagents import create_deep_agent
from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    StateBackend,
    StoreBackend,
)
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState
#from langgraph.store.postgres import AsyncPostgresStore

from config import OCR_OUTPUT_DIR, WORKSPACE
from ocr_extraction import DocumentAI
from prompts.agent_prompts import RESEARCH_PROMPT
from subagents import make_subagents
from tools.companies_house import get_companies_house_tools
from tools.filesystem import read_external_file
from tools.linkedin import get_linkedin_tools

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class State(MessagesState):
    """State shared across all graph nodes."""

    email_input: dict | None
    """Email payload from the Gmail ingest pipeline.

    Expected keys: ``from``, ``to``, ``subject``, ``body``, ``id``.
    The ``body`` field contains the applicant's loan application text.
    The ``from`` field is used as the ``case_number``.
    """

    case_number: str
    """Unique case identifier — also used as the sub-directory name under
    ``data/`` where source documents are stored."""

    documents: List[dict]
    """Serializable summaries of documents processed during the startup node.

    Each entry contains ``document_name``, ``document_type``, and
    ``ocr_output_path`` (absolute path to the persisted extraction JSON).
    The full extraction data is read from disk by the agents via
    :func:`~tools.filesystem.read_external_file`.
    """


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

def _make_backend(runtime):
    """Create a :class:`CompositeBackend` for the deep agent.

    Path routing:
        * ``/memories/``   → persistent :class:`StoreBackend` (survives turns)
                             namespace: ``("memory", <case_number>)``
        * ``/disk-files/`` → :class:`FilesystemBackend` rooted at WORKSPACE
        * everything else  → ephemeral :class:`StateBackend`
    """
    def _memory_namespace(ctx) -> tuple[str, ...]:
        # ctx.state is the deep-agent's own internal state and does not carry
        # the outer graph's case_number.  Read from RunnableConfig instead —
        # it is propagated intact through the entire invocation chain.
        config = getattr(ctx.runtime, "config", None) or {}
        case_number = config.get("configurable", {}).get("case_number") or "unknown"
        return ("memory", case_number)

    return CompositeBackend(
        default=StateBackend(runtime),
        routes={
            "/memories/": StoreBackend(runtime, namespace=_memory_namespace),
            # "/disk-files/": FilesystemBackend(
            #     root_dir=str(WORKSPACE), virtual_mode=True
            "/disk-files": StoreBackend(runtime, namespace="disk-files")

        },
    )




# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def startup_node(state: State) -> dict:
    """Parse, classify, extract, and persist all documents for the case.

    Reads source documents from ``<PROJECT_ROOT>/data/<case_number>/``,
    runs the Landing AI ADE pipeline on each file, and writes structured
    JSON extractions plus annotated PNGs to the shared workspace under
    ``ocr_output/<case_number>/``.

    When ``email_input`` is present in state, ``case_number`` is derived from
    the sender address (``email_input["from"]``) and the email body is injected
    as the first :class:`~langchain_core.messages.HumanMessage` so the
    assessment agent receives the full application text.

    Args:
        state: Current graph state.  Either ``case_number`` or ``email_input``
               must be populated.

    Returns:
        Partial state update with ``case_number``, ``documents``, and an
        initial ``messages`` entry when ``email_input`` is provided.
    """
    email_input = state.get("email_input") or {}
    # Prefer filesystem-safe case_number from ingest (matches data/<case_number>/); fall back to "from" or state
    case_number = (
        email_input.get("case_number")
        or email_input.get("from")
        or state.get("case_number", "unknown")
    )
    data_dir = WORKSPACE.parent.parent / "data" / case_number

    logger.info("━━━ [startup] case=%s", case_number)

    if not data_dir.exists():
        logger.warning("[startup] Document directory not found: %s", data_dir)
        update: dict = {"case_number": case_number, "documents": []}
        application_text = email_input.get("body", "")
        if application_text:
            update["messages"] = [HumanMessage(content=application_text)]
        return update

    source_files = [p for p in data_dir.iterdir() if p.is_file()]
    logger.info("[startup] Found %d source file(s) in %s", len(source_files), data_dir)

    documents = []
    for i, document_path in enumerate(source_files, start=1):
        logger.info(
            "[startup] (%d/%d) Parsing  → %s",
            i, len(source_files), document_path.name,
        )
        doc = DocumentAI(document_path, case_number=case_number)
        doc.parse()

        logger.info(
            "[startup] (%d/%d) Classifying → %s",
            i, len(source_files), document_path.name,
        )
        doc.classify()
        logger.info(
            "[startup] (%d/%d) Detected type: %s",
            i, len(source_files), doc.document_type,
        )

        logger.info(
            "[startup] (%d/%d) Extracting fields → %s",
            i, len(source_files), document_path.name,
        )
        doc.extract()

        # Persist to workspace/ocr_output/ so agents can read via /disk-files/
        doc.persist(output_root=OCR_OUTPUT_DIR)

        # Embed parsed chunks and store in PGVectorStore for RAG retrieval
        asyncio.run(doc.embed_and_store())

        # Store only serializable metadata — the full extraction JSON is on disk
        ocr_path = OCR_OUTPUT_DIR / case_number / f"{document_path.stem}_extraction.json"
        documents.append(
            {
                "document_name": document_path.name,
                "document_type": doc.document_type,
                "ocr_output_path": str(ocr_path),
            }
        )

        # documents.append(
        #     {
        #         "document_name": "5573DraftAccounts_extraction.json",
        #         "document_type": "annual_company_report",
        #         "ocr_output_path": "/Users/stevegoodman/dev/fionaa-be/data/workspace/ocr_output/stevejgoodman@gmail.com/5573DraftAccounts_extraction.json",
        #     }
        
        # logger.info(
        #     "[startup] (%d/%d) Done — extraction saved to %s",
        #     i, len(source_files), ocr_path,
        # )

    type_summary = ", ".join(d["document_type"] for d in documents) or "none"
    logger.info(
        "[startup] Complete — %d document(s) processed (%s)",
        len(documents), type_summary,
    )

    update: dict = {"case_number": case_number, "documents": documents}

    # Seed the conversation with the application text from the email body so
    # the assessment agent receives it as the first human message.
    application_text = email_input.get("body", "")
    if application_text:
        update["messages"] = [HumanMessage(content=application_text)]

    return update


def _route_after_start(state: State, config: RunnableConfig | None = None) -> str:
    """Route START to startup or assessment_deepagent based on configurable.run_without_ocr."""
    if config is None:
        config = {}
    run_without_ocr = config.get("configurable", {}).get("run_without_ocr", False)
    return "assessment_deepagent" if run_without_ocr else "startup"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

async def build_graph(
    run_without_internet_search: bool = False,
) -> tuple:
    """Build and compile the Fionaa assessment graph.

    Initialises the async MCP clients (LinkedIn, Companies House), assembles
    the deep-agent orchestrator, then compiles the :class:`StateGraph`.

    The compiled graph is returned without a custom checkpointer or store so
    that ``langgraph dev`` / LangGraph API can inject its own managed
    persistence layer.  The deep agent still uses its own internal
    SqliteStore + MemorySaver for cross-turn memory within a single run.

    Args:
        run_without_internet_search: If True, only eligibility and financial
            assessment subagents are used (no LinkedIn, Companies House, or
            internet search).

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph` ready for ``langgraph dev``.
    """
    logger.info("━━━ [build_graph] Initialising Fionaa assessment graph")

    # Internal persistence for the deep agent (not exposed to the outer graph).
    # We keep a reference to the context manager on the store itself so it is
    # not garbage-collected (which would close the underlying DB connection).
    # _pg_conn = (
    #     f"postgresql://postgres:{os.environ['PG_PASSWORD']}"
    #     f"@localhost/langchain"
    # )
    # _store_ctx = AsyncPostgresStore.from_conn_string(_pg_conn)
    # _store = await _store_ctx.__aenter__()
    # await _store.setup()
    # _store._ctx = _store_ctx  # prevent GC of the context manager
    # _checkpointer = MemorySaver()

    # Initialise MCP tool servers (async)
    logger.info("[build_graph] Connecting to LinkedIn MCP server…")
    li_tools = await get_linkedin_tools()
    logger.info("[build_graph] LinkedIn MCP ready — %d tool(s)", len(li_tools))

    logger.info("[build_graph] Connecting to Companies House MCP server…")
    ch_tools = await get_companies_house_tools()
    logger.info("[build_graph] Companies House MCP ready — %d tool(s)", len(ch_tools))

    # Build subagent configs
    subagents = make_subagents(
        li_tools, ch_tools, run_without_internet_search=run_without_internet_search
    )
    logger.info("[build_graph] %d subagent(s) configured", len(subagents))

    # Build the orchestrator deep agent (no LinkedIn/CH/internet tools when run_without_internet_search)
    orchestrator_tools = (
        [read_external_file]
        if run_without_internet_search
        else [read_external_file] + li_tools + ch_tools
    )
    _assessment_agent = create_deep_agent(
        model=init_chat_model("anthropic:claude-sonnet-4-20250514"),
        tools=orchestrator_tools,
        # store=_store,
        backend=_make_backend,
        # checkpointer=_checkpointer,
        subagents=subagents,
        system_prompt=RESEARCH_PROMPT,
    )

    logger.info("Graph compiled — nodes: startup → assessment_deepagent → END")

    # Assemble the graph
    builder = StateGraph(State)
    builder.add_node("startup", startup_node)
    builder.add_node("assessment_deepagent", _assessment_agent.ainvoke)
    builder.add_conditional_edges(
        START,
        _route_after_start,
        {"startup": "startup", "assessment_deepagent": "assessment_deepagent"},
    )
    builder.add_edge("startup", "assessment_deepagent")
    builder.add_edge("assessment_deepagent", END)

    # Pass the store and checkpointer so direct invocation (e.g. ingest.py) works.
    # langgraph dev will use its own managed persistence when deployed via the server.
    #graph = builder.compile(checkpointer=_checkpointer, store=_store)
    graph = builder.compile()

    logger.info("[build_graph] Ready")
    return graph

# Module-level compiled graph — referenced by langgraph.json as "graph.py:fionaa"
# When imported from within a running event loop (e.g. ingest.py) asyncio.run()
# would raise "cannot be called from a running event loop", so we detect that case
# and leave fionaa as None.  Callers must then await build_graph() directly.
try:
    asyncio.get_running_loop()
    fionaa = None  # async context — caller must use `await build_graph()`
except RuntimeError:
    fionaa = asyncio.run(build_graph())  # no loop running — safe for langgraph dev