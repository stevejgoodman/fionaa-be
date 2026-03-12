"""Chatbot LangGraph for case-scoped Q&A over assessment findings.

Input
- ``messages``    : conversation history (human + AI turns)
- ``case_number`` : identifies the case namespace in the shared store

Assessment findings are read from GCS bucket``<case_number>/reports/`` 

"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, TypedDict

from langgraph.store.memory import InMemoryStore
from langgraph.runtime import get_runtime

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from google.cloud.exceptions import NotFound

from backends.gcs_backend import GCSBackend

load_dotenv()   

logger = logging.getLogger(__name__)



class ChatbotState(TypedDict):
    """State for the Fionaa chatbot graph."""

    messages: Annotated[list, add_messages]
    case_number: str


# ---------------------------------------------------------------------------

# All tools read/write assessment findings in GCS under <case_number>/reports/.
# case_number is read from config["configurable"]["case_number"].
# ---------------------------------------------------------------------------


def _make_tools() -> list:
    """Return chatbot tools."""

    _gcs = GCSBackend()

    @tool
    def list_case_files(config: RunnableConfig) -> str:
        """List all assessment findings files available for this case.

        Returns a bullet list of file paths that can be fetched individually
        with the ``read_case_file`` tool.
        """
        case_number = config.get("configurable", {}).get("case_number", "unknown")
        prefix = f"/{case_number}/reports/"
        entries = _gcs.ls_info(prefix)
        files = [e["path"] for e in entries if not e.get("is_dir")]
        if not files:
            return f"No assessment files found for case '{case_number}'."
        lines = [f"- {f}" for f in files]
        return f"Assessment files for case '{case_number}':\n" + "\n".join(lines)

    @tool
    def read_case_file(path: str, config: RunnableConfig) -> str:
        """Read an assessment findings file from GCS.

        Args:
            path: The file path exactly as returned by ``list_case_files``
                  (e.g. ``/case123/reports/eligibility_findings.md``).
        """
        case_number = config.get("configurable", {}).get("case_number", "unknown")
        clean_path = "/" + path.lstrip("/")
        expected_prefix = f"/{case_number}/reports/"
        if not clean_path.startswith(expected_prefix):
            clean_path = f"{expected_prefix}{path.lstrip('/')}"
        return _gcs.read(clean_path)

    @tool
    def edit_file(path: str, old_text: str, new_text: str, config: RunnableConfig) -> str:
        """Edit an assessment findings file in GCS by replacing specific text.

        Use this to make targeted in-place edits: correct values, update names,
        fix figures, or annotate specific lines.  The first occurrence of
        ``old_text`` is replaced with ``new_text`` and the result is saved back
        to GCS.

        To append a new section, set ``old_text`` to the last line(s) of the file
        and include that same text at the start of ``new_text`` followed by your
        new content.

        Always call ``read_case_file`` first so you have the exact text to match.

        Args:
            path: The file path exactly as returned by ``list_case_files``
                  (e.g. ``/case123/reports/eligibility_findings.md``).
            old_text: The exact literal text to find and replace (must exist in the file).
            new_text: The replacement text.
        """
        case_number = config.get("configurable", {}).get("case_number", "unknown")
        clean_path = "/" + path.lstrip("/")
        expected_prefix = f"/{case_number}/reports/"
        if not clean_path.startswith(expected_prefix):
            clean_path = f"{expected_prefix}{path.lstrip('/')}"
        key = clean_path.lstrip("/")
        blob = _gcs._bucket.blob(key)
        try:
            existing = blob.download_as_text(encoding="utf-8")
        except NotFound:
            return f"Error: File '{clean_path}' not found. Use list_case_files to see available files."
        if old_text not in existing:
            return (
                f"Error: The text to replace was not found in '{clean_path}'. "
                "Use read_case_file to check the exact content before editing."
            )
        updated = existing.replace(old_text, new_text, 1)
        blob.upload_from_string(updated, content_type="text/plain; charset=utf-8")
        return f"File '{clean_path}' updated successfully."

    @tool
    def search_documents(
        query: str,
        config: RunnableConfig,
    ) -> str:
        """Search the applicant's original document chunks using semantic similarity.

        Use this when you need to answer a specific question about the raw
        content of submitted documents (bank statements, annual accounts) that
        is not covered by the pre-written assessment findings files.

        Args:
            query: Natural-language question or phrase, e.g.
                   "monthly closing balance March 2024" or "total revenue".
        """
        import os
        from langgraph.store.memory import InMemoryStore as _InMemoryStore

        case_number = config.get("configurable", {}).get("case_number", "unknown")
        store = get_runtime().store
        store_type = type(store).__name__ if store else "None"
        logger.info(
            "[search_documents] store=%s case=%s query=%r",
            store_type, case_number, query,
        )

        # When running in-process (local dev) the store is an empty InMemoryStore.
        # Fall back to the LangGraph Platform store via the HTTP SDK so that chunks
        # written by the fionaa graph on the platform are still searchable.
        use_sdk_fallback = store is None or isinstance(store, _InMemoryStore)

        if use_sdk_fallback:
            langgraph_url = os.environ.get("LANGGRAPH_URL", "").strip()
            langsmith_api_key = os.environ.get("LANGSMITH_API_KEY", "").strip()
            if not langgraph_url:
                return "Document store is not available (LANGGRAPH_URL not configured)."
            try:
                from langgraph_sdk import get_sync_client
                sdk_client = get_sync_client(url=langgraph_url, api_key=langsmith_api_key or None)
                response = sdk_client.store.search_items(
                    ("cases", case_number), query=query, limit=1
                )
                raw_items = response.get("items", [])
                logger.info("[search_documents] sdk fallback results=%d", len(raw_items))
            except Exception as exc:
                logger.warning("[search_documents] sdk fallback failed: %s", exc)
                return f"Document store search failed: {exc}"

            if not raw_items:
                return f"No document chunks found for case '{case_number}' matching: {query}"

            lines = [f"Found {len(raw_items)} chunk(s) for query: '{query}'\n"]
            for i, item in enumerate(raw_items, start=1):
                v = item.get("value", {})
                score = item.get("score")
                score_str = f"{score:.3f}" if score is not None else "n/a"
                chunk_text = (
                    f"--- Chunk {i} (score={score_str}) ---\n"
                    f"Source: {v.get('document_name', 'unknown')}  "
                    f"| Type: {v.get('document_type', '?')}  "
                    f"| Page: {v.get('page_num', '?')}  "
                    f"| Chunk type: {v.get('chunk_type', '?')}\n"
                    f"{v.get('text', '')}\n"
                )
                bbox_left = v.get("bbox_left")
                logger.info(
                    "[search_documents] chunk=%d doc=%s bbox_left=%s",
                    i, v.get("document_name"), bbox_left,
                )
                if bbox_left is not None:
                    chunk_text += (
                        f"[VISUAL_REF:case={case_number}"
                        f"|doc={v.get('document_name', 'unknown')}"
                        f"|page={v.get('page_num', 0)}"
                        f"|bbox={bbox_left:.4f},{v.get('bbox_top', 0):.4f}"
                        f",{v.get('bbox_right', 1):.4f},{v.get('bbox_bottom', 1):.4f}]\n"
                    )
                lines.append(chunk_text)
            return "\n".join(lines)

        # Platform store is available — use it directly.
        results = store.search(("cases", case_number), query=query, limit=1)
        logger.info("[search_documents] results=%d", len(results) if results else 0)

        if not results:
            return f"No document chunks found for case '{case_number}' matching: {query}"

        lines = [f"Found {len(results)} chunk(s) for query: '{query}'\n"]
        for i, item in enumerate(results, start=1):
            v = item.value
            score = f"{item.score:.3f}" if item.score is not None else "n/a"
            chunk_text = (
                f"--- Chunk {i} (score={score}) ---\n"
                f"Source: {v.get('document_name', 'unknown')}  "
                f"| Type: {v.get('document_type', '?')}  "
                f"| Page: {v.get('page_num', '?')}  "
                f"| Chunk type: {v.get('chunk_type', '?')}\n"
                f"{v.get('text', '')}\n"
            )
            bbox_left = v.get("bbox_left")
            logger.info(
                "[search_documents] chunk=%d doc=%s bbox_left=%s",
                i, v.get("document_name"), bbox_left,
            )
            if bbox_left is not None:
                chunk_text += (
                    f"[VISUAL_REF:case={case_number}"
                    f"|doc={v.get('document_name', 'unknown')}"
                    f"|page={v.get('page_num', 0)}"
                    f"|bbox={bbox_left:.4f},{v.get('bbox_top', 0):.4f}"
                    f",{v.get('bbox_right', 1):.4f},{v.get('bbox_bottom', 1):.4f}]\n"
                )
            lines.append(chunk_text)
        return "\n".join(lines)

    return [list_case_files, read_case_file, edit_file, search_documents]


_SYSTEM_PROMPT = """\
You are Fionaa, an AI assistant for loan application case review.

You have access to the assessment findings stored in GCS for the current
case via the provided tools.

Guidelines:
- Call ``list_case_files`` first if you are unsure what information is available.
- Use ``read_case_file`` to fetch the full content of a specific findings file.
- Use ``search_documents`` when asked a specific question about the applicant's
  raw submitted documents (e.g. exact figures, dates, or passages not present
  in the findings files).
- Be concise and factual; do not speculate beyond the available case evidence.
- To edit or annotate a report, first call ``read_case_file`` to get the exact
  current text, then call ``edit_file`` with the exact ``old_text`` to replace
  and the ``new_text`` to substitute.  Never guess at the exact text — always
  read the file first.
- When quoting content from ``search_documents`` results, you MUST copy any
  ``[VISUAL_REF:...]`` markers that appear in the chunk text exactly as-is into
  your response, immediately after the passage or figure you are referencing.
  Do not paraphrase, shorten, or omit these markers — they are machine-readable
  and will be used to display the source document image to the user.
"""



def _make_chatbot_node(model):
    async def chatbot(state: ChatbotState, config: RunnableConfig) -> dict:
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + list(
            state["messages"]
        )
        response = await model.ainvoke(messages, config=config)
        return {"messages": [response]}

    return chatbot




async def build_chatbot_graph() -> object:
    """Build and compile the Fionaa chatbot graph.

    Assessment findings are read from GCS and notes are appended back to GCS
    report files.  Conversation history is held in a MemorySaver checkpointer
    keyed by ``thread_id`` (set to ``"chatbot-{case_number}"`` by the caller).

    Compiled with an InMemoryStore as a placeholder — LangGraph Platform
    replaces it with the shared managed store (configured in langgraph.json)
    at runtime, so ``search_documents`` reads the same chunks that the fionaa
    startup graph wrote.

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph`.
    """
    logger.info("━━━ [build_chatbot_graph] Initialising")

    tools = _make_tools()
    model = init_chat_model("anthropic:claude-haiku-4-5-20251001").bind_tools(tools)

    builder = StateGraph(ChatbotState)
    builder.add_node("chatbot", _make_chatbot_node(model))
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "chatbot")
    builder.add_conditional_edges("chatbot", tools_condition)
    builder.add_edge("tools", "chatbot")
    # tools_condition routes to END when there are no pending tool calls

    graph = builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())
    logger.info("[build_chatbot_graph] Ready")
    return graph


# Module-level compiled graph — referenced by langgraph.json as "chatbot_graph.py:chatbot"
# Mirror the same asyncio detection used in graph.py.
try:
    asyncio.get_running_loop()
    chatbot = None  # async context — caller must use `await build_chatbot_graph()`
except RuntimeError:
    chatbot = asyncio.run(build_chatbot_graph())
