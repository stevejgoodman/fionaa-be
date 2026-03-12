"""LangGraph orchestration for the Fionaa loan application assessment pipeline.
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
    StateBackend,
)

from backends.gcs_backend import GCSBackend, make_gcs_client, setup_google_credentials
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.graph.message import MessagesState
#from langgraph.store.postgres import AsyncPostgresStore

from config import DATA_DIR, GCS_LOAN_APPLICATION_PREFIX
from ocr_extraction import DocumentAI
from prompts.agent_prompts import RESEARCH_PROMPT
from subagents import make_subagents
from tools.companies_house import get_companies_house_tools
from tools.document_retrieval import search_document_chunks
from tools.filesystem import read_external_file
from tools.linkedin import get_linkedin_tools

load_dotenv()

logger = logging.getLogger(__name__)



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


def _make_backend(runtime):
    """Create a :class:`CompositeBackend` for the deep agent.

    Path routing:
        * ``/reports/``    → :class:`GCSBackend` at ``<case_number>/reports/`` in GCS
        * ``/disk-files/`` → :class:`GCSBackend` at bucket root
        * everything else  → ephemeral :class:`StateBackend`
    """
    config = getattr(runtime, "config", None) or {}
    case_number = config.get("configurable", {}).get("case_number") or "unknown"

    return CompositeBackend(
        default=StateBackend(runtime),
        routes={
            "/reports/": GCSBackend(prefix=f"{case_number}/reports"),
            "/disk-files/": GCSBackend(),
        },
    )



def _get_source_files(
    case_number: str,
) -> tuple[list, object]:
    """Locate source documents for *case_number*, preferring local disk then GCS.

    When ``GOOGLE_CLOUD_PROJECT`` is set and the local landing-zone directory
    does not exist, blobs under ``<case_number>/loan_application/`` in the GCS
    bucket are downloaded to a temporary directory so that DocumentAI can
    process them as normal local files.

    Returns:
        ``(source_files, tmpdir)`` where *source_files* is a list of
        :class:`~pathlib.Path` objects and *tmpdir* is a
        :class:`~tempfile.TemporaryDirectory` that must be kept alive until
        processing is complete (``None`` when local files are used).
    """
    import tempfile
    from pathlib import Path as _Path

    data_dir = DATA_DIR / case_number
    if data_dir.exists():
        files = [p for p in data_dir.iterdir() if p.is_file()]
        logger.info("[startup] Found %d local source file(s) in %s", len(files), data_dir)
        return files, None

    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        logger.warning("[startup] Local dir missing and GOOGLE_CLOUD_PROJECT not set — no source files")
        return [], None

    bucket_name = os.environ.get("BUCKET_NAME", "")
    if not bucket_name:
        logger.warning("[startup] Local dir missing and BUCKET_NAME not set — no source files")
        return [], None

    prefix = f"{case_number}/{GCS_LOAN_APPLICATION_PREFIX}/"
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    gcs = make_gcs_client(project=project)
    blobs = [
        b for b in gcs.list_blobs(bucket_name, prefix=prefix)
        if not b.name.endswith("/")
    ]

    if not blobs:
        logger.warning("[startup] No blobs found in GCS at %s", prefix)
        return [], None

    tmpdir = tempfile.TemporaryDirectory(prefix="fionaa_startup_")
    files = []
    for blob in blobs:
        filename = blob.name.split("/")[-1]
        local_path = _Path(tmpdir.name) / filename
        blob.download_to_filename(str(local_path))
        files.append(local_path)
        logger.info("[startup] Downloaded from GCS: %s → %s", blob.name, local_path)

    return files, tmpdir


def startup_node(state: State, *, store: BaseStore | None = None) -> dict:
    """Parse, classify, extract, and persist all documents for the case.

    Source documents are resolved in order:
    1. Local ``data/<case_number>/`` directory (local dev / CI).
    2. GCS ``<case_number>/loan_application/`` (cloud deployment — files
       uploaded there by ``ingest.py`` before graph invocation).

    Runs the Landing AI ADE pipeline on each file and uploads structured JSON
    extractions plus annotated PNGs to GCS under ``<case_number>/ocr_output/``.

    When ``email_input`` is present in state, ``case_number`` is derived from
    the sender address and the email body is injected as the first
    :class:`~langchain_core.messages.HumanMessage`.

    Args:
        state: Current graph state.  Either ``case_number`` or ``email_input``
               must be populated.

    Returns:
        Partial state update with ``case_number``, ``documents``, and an
        initial ``messages`` entry when ``email_input`` is provided.
    """
    email_input = state.get("email_input") or {}
    case_number = (
        email_input.get("case_number")
        or email_input.get("from")
        or state.get("case_number", "unknown")
    )

    logger.info("━━━ [startup] case=%s", case_number)

    source_files, tmpdir = _get_source_files(case_number)

    if not source_files:
        update: dict = {"case_number": case_number, "documents": []}
        application_text = email_input.get("body", "")
        if application_text:
            update["messages"] = [HumanMessage(content=application_text)]
        return update

    # Upload local files to GCS only when they came from local disk
    # (GCS-sourced files are already in the bucket).
    if tmpdir is None and os.environ.get("BUCKET_NAME"):
        bucket_name = os.environ["BUCKET_NAME"]
        gcs = make_gcs_client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        bucket = gcs.bucket(bucket_name)
        for document_path in source_files:
            loan_app_key = f"{case_number}/{GCS_LOAN_APPLICATION_PREFIX}/{document_path.name}"
            bucket.blob(loan_app_key).upload_from_filename(str(document_path))
            logger.info("[startup] Uploaded source doc to GCS: %s", loan_app_key)

    try:
        documents = []
        for i, document_path in enumerate(source_files, start=1):
            logger.info("[startup] (%d/%d) Parsing  → %s", i, len(source_files), document_path.name)
            doc = DocumentAI(document_path, case_number=case_number)
            doc.parse()

            logger.info("[startup] (%d/%d) Classifying → %s", i, len(source_files), document_path.name)
            doc.classify()
            logger.info("[startup] (%d/%d) Detected type: %s", i, len(source_files), doc.document_type)

            logger.info("[startup] (%d/%d) Extracting fields → %s", i, len(source_files), document_path.name)
            doc.extract()

            ocr_virtual_path = doc.persist()
            if store is not None:
                doc.embed_and_store(store)
            else:
                logger.warning("[startup] No store available — skipping embed_and_store for %s", document_path.name)
            logger.info("[startup] (%d/%d) OCR output at %s", i, len(source_files), ocr_virtual_path)

            documents.append(
                {
                    "document_name": document_path.name,
                    "document_type": doc.document_type,
                    "ocr_output_path": ocr_virtual_path,
                }
            )
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()

    type_summary = ", ".join(d["document_type"] for d in documents) or "none"
    logger.info("[startup] Complete — %d document(s) processed (%s)", len(documents), type_summary)

    update: dict = {"case_number": case_number, "documents": documents}
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

    # Ensure GOOGLE_APPLICATION_CREDENTIALS is set before any IAM/GCS clients
    # are constructed.  In cloud deployments the service account JSON is passed
    # via GOOGLE_CREDENTIALS_JSON and written to a temp file here.
    setup_google_credentials()

    _checkpointer = MemorySaver()
    _store = InMemoryStore()

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
        [read_external_file, search_document_chunks]
        if run_without_internet_search
        else [read_external_file, search_document_chunks] + ch_tools #+ li_tools
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

    graph = builder.compile(checkpointer=_checkpointer, store=_store)

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

