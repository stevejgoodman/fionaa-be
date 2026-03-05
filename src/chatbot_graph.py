"""Chatbot LangGraph for case-scoped Q&A over assessment findings.

Graph topology
--------------
START → chatbot ─┬─[tool calls?]─→ tools → chatbot
                 └─[done]─────────→ END

Input state
-----------
- ``messages``    : conversation history (human + AI turns)
- ``case_number`` : identifies the case namespace in the shared store

The chatbot tools use psycopg directly (sync) to read/write the ``store``
table, which is the same PostgreSQL table used by the assessment pipeline's
AsyncPostgresStore.  Using sync psycopg avoids asyncio event-loop affinity
issues: LangGraph's ToolNode runs sync tools in a thread-pool executor, so
no event loop is involved in the tool calls at all.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Annotated, TypedDict

import psycopg
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

#from vector_store import get_store

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
# Store-scoped tool factory
#
# Tools are sync functions that call psycopg directly — the same approach used
# by load_db_memories() in app.py.  LangGraph's async ToolNode runs sync tools
# via run_in_executor (a thread-pool), so there is no event loop in scope
# during the DB calls, which eliminates "Future attached to different loop"
# errors that arise from AsyncPostgresStore's internal batcher.
#
# case_number is read from config["configurable"]["case_number"], which the
# app sets on every graph.ainvoke() call alongside the thread_id.
# ---------------------------------------------------------------------------

# LangGraph stores namespace tuples as dot-joined strings in the prefix column.
# ("memory", "user@example.com") → prefix = "memory.user@example.com"
_NS_SEP = "."


def _make_tools(pg_conn_string: str) -> list:
    """Return the three store tools bound to *pg_conn_string* via closure."""

    @tool
    def list_memories(config: RunnableConfig) -> str:
        """List all memory and findings entries saved for this case.

        Returns a bullet list of available entry keys that can be fetched
        individually with the ``read_memory`` tool.
        """
        case_number = config.get("configurable", {}).get("case_number", "unknown")
        prefix = f"memory{_NS_SEP}{case_number}"
        with psycopg.connect(pg_conn_string, autocommit=True) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT key FROM store WHERE prefix = %s ORDER BY key",
                    (prefix,),
                )
                rows = cur.fetchall()
        if not rows:
            return f"No memory entries found for case '{case_number}'."
        lines = [f"- {row['key']}" for row in rows]
        return f"Memory entries for case '{case_number}':\n" + "\n".join(lines)

    @tool
    def read_memory(key: str, config: RunnableConfig) -> str:
        """Read a specific memory or findings entry by its key.

        Args:
            key: The entry key exactly as returned by ``list_memories``
                 (e.g. ``"eligibility_findings.md"``).
        """
        case_number = config.get("configurable", {}).get("case_number", "unknown")
        prefix = f"memory{_NS_SEP}{case_number}"
        with psycopg.connect(pg_conn_string, autocommit=True) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT value FROM store WHERE prefix = %s AND key = %s",
                    (prefix, key),
                )
                row = cur.fetchone()
        if row is None:
            return f"No entry found for key '{key}' in case '{case_number}'."
        value = row["value"]
        # psycopg deserialises JSONB → dict; content is under the "content" key
        if isinstance(value, dict):
            return value.get("content", str(value))
        return str(value)

    @tool
    def write_memory(key: str, content: str, config: RunnableConfig) -> str:
        """Write or update a memory entry for this case.

        Args:
            key: Identifier for the entry (e.g. ``"chatbot_notes.md"``).
            content: Full text content to store.
        """
        case_number = config.get("configurable", {}).get("case_number", "unknown")
        prefix = f"memory{_NS_SEP}{case_number}"
        with psycopg.connect(pg_conn_string, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO store (prefix, key, value, created_at, updated_at)
                    VALUES (%s, %s, %s, now(), now())
                    ON CONFLICT (prefix, key) DO UPDATE
                        SET value = EXCLUDED.value, updated_at = now()
                    """,
                    (prefix, key, Jsonb({"content": content})),
                )
        return f"Saved '{key}' to memory for case '{case_number}'."

    return [list_memories, read_memory, write_memory]


@tool
async def search_documents(query: str, config: RunnableConfig) -> str:
    """Search the parsed document chunks for this case using semantic similarity.

    Use this tool to find relevant passages from the documents uploaded for the
    current case (bank statements, annual accounts, etc.).

    Args:
        query: Natural language question or search phrase.
    """
    case_number = config.get("configurable", {}).get("case_number", "unknown")

    store = await get_store()
    docs = await store.asimilarity_search(
        query,
        k=5,
        filter={"case_number": case_number},
    )

    if not docs:
        return f"No relevant document chunks found for case '{case_number}'."

    parts = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        header = (
            f"[Chunk {i} | type={meta.get('chunk_type', '?')} "
            f"| page={meta.get('page_num', '?')}]"
        )
        parts.append(f"{header}\n{doc.page_content}")

    return "\n\n---\n\n".join(parts)


_SYSTEM_PROMPT = """\
You are Fionaa, an AI assistant for loan application case review.

You have access to the assessment findings and notes stored for the current
case via the provided tools.

Guidelines:
- Call ``list_memories`` first if you are unsure what information is available.
- Use ``search_documents`` to find relevant passages from the uploaded documents
  (bank statements, annual accounts, etc.) when you need raw source evidence.
- Be concise and factual; do not speculate beyond the available case evidence.
- When asked to save notes or updates, use ``write_memory``.
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

    Tools use psycopg sync to read/write the shared store table directly.
    Conversation history is held in a MemorySaver checkpointer keyed by
    ``thread_id`` (set to ``"chatbot-{case_number}"`` by the caller).

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph`.
    """
    logger.info("━━━ [build_chatbot_graph] Initialising")

    pg_conn_string = (
        f"postgresql://postgres:{os.environ['PG_PASSWORD']}"
        f"@localhost/langchain"
    )

    tools = _make_tools(pg_conn_string) + [search_documents]
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
