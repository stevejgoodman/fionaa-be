"""Chatbot LangGraph for case-scoped Q&A over assessment findings.

Graph topology
--------------
START → chatbot ─┬─[tool calls?]─→ tools → chatbot
                 └─[done]─────────→ END

Input state
-----------
- ``messages``    : conversation history (human + AI turns)
- ``case_number`` : identifies the case namespace in the shared store

Assessment findings are read from GCS (``<case_number>/reports/`` in the
bucket).  Ephemeral chatbot notes are stored in an :class:`InMemoryStore`
and are not persisted after the process exits.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.store.memory import InMemoryStore

from backends.gcs_backend import GCSBackend

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class ChatbotState(TypedDict):
    """State for the Fionaa chatbot graph."""

    messages: Annotated[list, add_messages]
    case_number: str


# ---------------------------------------------------------------------------
# Tool factory
#
# GCS tools read assessment findings from <case_number>/reports/ in the
# bucket.  Note tools read/write to an InMemoryStore for ephemeral session
# notes.  case_number is read from config["configurable"]["case_number"].
# ---------------------------------------------------------------------------


def _make_tools(store: InMemoryStore) -> list:
    """Return tools bound to *store* via closure."""

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
    def write_note(key: str, content: str, config: RunnableConfig) -> str:
        """Write or update an ephemeral note for this chat session.

        Notes are stored in memory only and are not persisted after the
        session ends.

        Args:
            key: Identifier for the note (e.g. ``"summary"``).
            content: Full text content to store.
        """
        case_number = config.get("configurable", {}).get("case_number", "unknown")
        store.put(("chatbot_notes", case_number), key, {"content": content})
        return f"Saved note '{key}' for case '{case_number}'."

    @tool
    def read_note(key: str, config: RunnableConfig) -> str:
        """Read an ephemeral note written earlier in this session.

        Args:
            key: The note key as used with ``write_note``.
        """
        case_number = config.get("configurable", {}).get("case_number", "unknown")
        item = store.get(("chatbot_notes", case_number), key)
        if item is None:
            return f"No note found for key '{key}' in case '{case_number}'."
        return item.value.get("content", str(item.value))

    return [list_case_files, read_case_file, write_note, read_note]


_SYSTEM_PROMPT = """\
You are Fionaa, an AI assistant for loan application case review.

You have access to the assessment findings stored in GCS for the current
case via the provided tools.

Guidelines:
- Call ``list_case_files`` first if you are unsure what information is available.
- Use ``read_case_file`` to fetch the full content of a specific findings file.
- Be concise and factual; do not speculate beyond the available case evidence.
- When asked to save notes or summaries, use ``write_note``.
"""


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def _make_chatbot_node(model):
    async def chatbot(state: ChatbotState, config: RunnableConfig) -> dict:
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + list(
            state["messages"]
        )
        response = await model.ainvoke(messages, config=config)
        return {"messages": [response]}

    return chatbot


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


async def build_chatbot_graph() -> object:
    """Build and compile the Fionaa chatbot graph.

    Assessment findings are read from GCS.  Ephemeral notes are stored in
    an InMemoryStore.  Conversation history is held in a MemorySaver
    checkpointer keyed by ``thread_id`` (set to ``"chatbot-{case_number}"``
    by the caller).

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph`.
    """
    logger.info("━━━ [build_chatbot_graph] Initialising")

    _store = InMemoryStore()
    tools = _make_tools(_store)
    model = init_chat_model("anthropic:claude-sonnet-4-20250514").bind_tools(tools)

    builder = StateGraph(ChatbotState)
    builder.add_node("chatbot", _make_chatbot_node(model))
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "chatbot")
    builder.add_conditional_edges("chatbot", tools_condition)
    builder.add_edge("tools", "chatbot")
    # tools_condition routes to END when there are no pending tool calls

    graph = builder.compile(checkpointer=MemorySaver())
    logger.info("[build_chatbot_graph] Ready")
    return graph


# Module-level compiled graph — referenced by langgraph.json as "chatbot_graph.py:chatbot"
# Mirror the same asyncio detection used in graph.py.
try:
    asyncio.get_running_loop()
    chatbot = None  # async context — caller must use `await build_chatbot_graph()`
except RuntimeError:
    chatbot = asyncio.run(build_chatbot_graph())
