"""Fionaa - File, Memory Viewer, and Chat application."""

import asyncio
import base64
import json
import os
import sys
import threading
from pathlib import Path

import psycopg
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
WORKSPACE_DIR = PROJECT_ROOT / "data" / "workspace"

_logo_b64 = base64.b64encode((PROJECT_ROOT / "logo.png").read_bytes()).decode()

# src/ on path so chatbot_graph can be imported without installing as a package
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _pg_conn_string() -> str:
    """Build the PostgreSQL connection string from the environment."""
    password = os.environ.get("PG_PASSWORD", "")
    return f"postgresql://postgres:{password}@localhost/langchain"


RENDERABLE_EXTS = {".txt", ".md", ".json", ".pdf", ".jpg", ".jpeg", ".png"}


# ── Persistent async event loop + chatbot graph ───────────────────────────────
# Streamlit is synchronous; the chatbot graph is async.
#
# The loop and the graph are cached TOGETHER as a single @st.cache_resource so
# they are always the same pair.  If they were separate, Streamlit script
# reloads would recreate the module-level loop while keeping the old cached
# graph, causing "Future attached to a different loop" errors because the
# AsyncPostgresStore's internal futures are bound to whichever loop was running
# when the store was initialised.


@st.cache_resource
def _get_loop_and_chatbot():
    """Create a persistent event loop and build the chatbot graph (once per process)."""
    from chatbot_graph import build_chatbot_graph  # noqa: PLC0415

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    future = asyncio.run_coroutine_threadsafe(build_chatbot_graph(), loop)
    graph = future.result(timeout=120)
    return loop, graph


def _run_async(coro):
    """Run *coro* on the cached background loop and block until the result is ready."""
    loop, _ = _get_loop_and_chatbot()
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=300)


def _get_chatbot():
    _, graph = _get_loop_and_chatbot()
    return graph


# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Fionaa",
    page_icon="🔵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    /* Hide deploy button, hamburger menu and Streamlit's own header bar */
    #MainMenu { visibility: hidden; }
    .stDeployButton { display: none; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stHeader"] { display: none; }

    /* Gradient header bar */
    .fionaa-header {
        background: linear-gradient(135deg, #1565C0 0%, #1E88E5 50%, #42A5F5 100%);
        color: white;
        padding: 14px 24px;
        border-radius: 12px;
        margin-bottom: 18px;
        display: flex;
        align-items: center;
        gap: 12px;
        box-shadow: 0 4px 16px rgba(30,136,229,0.25);
    }

    /* Make Streamlit's wrapper around the header sticky */
    [data-testid="stMainBlockContainer"] > div:first-child {
        position: sticky;
        top: 0;
        z-index: 999;
        background: white;
        padding-bottom: 4px;
    }
    .fionaa-header h1 {
        margin: 0;
        font-size: 1.8rem;
        font-weight: 700;
        letter-spacing: 1px;
    }
    .fionaa-header p {
        margin: 0;
        font-size: 0.85rem;
        opacity: 0.85;
    }

    /* Panel headings */
    .panel-heading {
        background: linear-gradient(90deg, #1E88E5, #42A5F5);
        color: white;
        padding: 7px 14px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 0.85rem;
        letter-spacing: 0.5px;
        margin-bottom: 10px;
        text-transform: uppercase;
    }

    /* File tree items */
    .stButton {
        margin-bottom: 0 !important;
        margin-top: 0 !important;
    }
    .stButton > button {
        text-align: left !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        color: #1A2D4A;
        padding: 3px 0;
        font-size: 0.62rem;
    }
    .stButton > button:hover,
    .stButton > button:focus,
    .stButton > button:active {
        color: #1E88E5;
        background: rgba(30,136,229,0.08) !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        border-radius: 5px;
    }


    /* Main content card */
    .content-card {
        background: white;
        border-radius: 10px;
        padding: 20px;
        border: 1px solid #BBDEFB;
        box-shadow: 0 2px 8px rgba(30,136,229,0.08);
        min-height: 500px;
    }

    /* Divider between panels */
    .panel-divider {
        border-left: 2px solid #BBDEFB;
        height: 100%;
    }

    /* File icon colors */
    .icon-pdf  { color: #E53935; }
    .icon-img  { color: #8E24AA; }
    .icon-json { color: #F57C00; }
    .icon-md   { color: #2E7D32; }
    .icon-txt  { color: #546E7A; }
    .icon-dir  { color: #1E88E5; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Session state ────────────────────────────────────────────────────────────

if "selected_file" not in st.session_state:
    st.session_state.selected_file = None
if "selected_source" not in st.session_state:
    st.session_state.selected_source = None  # "workspace" | "memory"
if "selected_memory_key" not in st.session_state:
    st.session_state.selected_memory_key = None   # (prefix, key) tuple
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = {}  # {case_number: [{"role": ..., "content": ...}]}


# ── Helpers ──────────────────────────────────────────────────────────────────


def file_icon(path: Path) -> str:
    """Return an emoji icon for a given file path."""
    if path.is_dir():
        return "📁"
    ext = path.suffix.lower()
    return {
        ".pdf": "📄",
        ".jpg": "🖼️",
        ".jpeg": "🖼️",
        ".png": "🖼️",
        ".json": "📋",
        ".md": "📝",
        ".txt": "🗒️",
    }.get(ext, "📎")


def load_workspace_tree(root: Path) -> dict:
    """Recursively build a dict tree of the workspace directory."""
    tree = {}
    if not root.exists():
        return tree
    for item in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if item.is_dir():
            tree[item] = load_workspace_tree(item)
        elif item.suffix.lower() in RENDERABLE_EXTS:
            tree[item] = None
    return tree


def render_tree(tree: dict, depth: int = 0, top_dirs_as_expanders: bool = False) -> None:
    """Render nested workspace tree as clickable buttons.

    When *top_dirs_as_expanders* is True, directories at depth 0 are rendered
    as collapsible ``st.expander`` widgets instead of inline headings.
    """
    for path, children in tree.items():
        indent = "&nbsp;" * (depth * 4)
        label = f"{indent}{file_icon(path)} {path.name}"
        if children is not None:
            if top_dirs_as_expanders and depth == 0:
                with st.expander(f"📁 {path.name}", expanded=True):
                    render_tree(children, depth + 1)
            else:
                st.markdown(
                    f"<div style='font-size:0.62rem;color:#1565C0;padding:2px 0;font-weight:600'>"
                    f"{label}</div>",
                    unsafe_allow_html=True,
                )
                render_tree(children, depth + 1)
        else:
            if st.button(label, key=f"ws_{path}", use_container_width=True):
                st.session_state.selected_file = path
                st.session_state.selected_source = "workspace"
                st.rerun()


def load_db_memories() -> list[dict]:
    """Load all memory records from the PostgreSQL store."""
    try:
        with psycopg.connect(
            _pg_conn_string(), autocommit=True, row_factory=psycopg.rows.dict_row
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT prefix, key, value, updated_at FROM store ORDER BY prefix, key"
                )
                return [
                    {
                        "prefix": r["prefix"],
                        "key": r["key"],
                        "value": r["value"],   # psycopg returns JSONB as a Python dict
                        "updated_at": r["updated_at"],
                    }
                    for r in cur.fetchall()
                ]
    except Exception as exc:
        st.sidebar.warning(f"Memories unavailable: {exc}")
        return []


def parse_memory_value(raw) -> str | None:
    """Extract text content from a memory store value.

    Accepts a Python dict (psycopg JSONB deserialization), a JSON string,
    or raw bytes — all produced by different store backends.
    """
    if raw is None:
        return None
    # psycopg deserialises JSONB → dict automatically
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="replace")
            data = json.loads(raw)
        except Exception:
            return str(raw)
    content = data.get("content", data)
    if isinstance(content, list):
        return "\n".join(str(line) for line in content)
    return str(content)


def render_file_content(path: Path) -> None:
    """Render a workspace file in the main pane."""
    ext = path.suffix.lower()
    st.markdown(
        f"<div style='font-size:0.78rem;color:#546E7A;margin-bottom:8px'>"
        f"📂 {path.relative_to(PROJECT_ROOT)}</div>",
        unsafe_allow_html=True,
    )

    if ext in (".jpg", ".jpeg", ".png"):
        st.image(str(path), use_container_width=True)

    elif ext == ".pdf":
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'width="100%" height="700" style="border:none;border-radius:8px;"></iframe>',
            unsafe_allow_html=True,
        )

    elif ext == ".md":
        st.markdown(path.read_text(encoding="utf-8", errors="replace"))

    elif ext == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            st.json(data)
        except json.JSONDecodeError:
            st.code(path.read_text(encoding="utf-8", errors="replace"), language="json")

    else:  # .txt and anything else
        st.text(path.read_text(encoding="utf-8", errors="replace"))


def _parse_prefix(prefix: str) -> tuple[str, str]:
    """Split a dot-joined namespace prefix into (namespace_type, case_id).

    ``"memory.stevejgoodman@gmail.com"`` → ``("memory", "stevejgoodman@gmail.com")``
    ``"filesystem"``                      → ``("filesystem", "")``
    """
    parts = prefix.split(".", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")


def render_memory_content(record: dict) -> None:
    """Render a memory store record in the main pane."""
    ns_type, case_id = _parse_prefix(record["prefix"])
    breadcrumb = f"🧠 {ns_type}"
    if case_id:
        breadcrumb += f" &nbsp;›&nbsp; <b>{case_id}</b>"
    breadcrumb += f" &nbsp;›&nbsp; {record['key'].lstrip('/')}"
    st.markdown(
        f"<div style='font-size:0.78rem;color:#546E7A;margin-bottom:8px'>{breadcrumb}</div>",
        unsafe_allow_html=True,
    )
    text = parse_memory_value(record["value"])
    if text:
        # Try to detect if it looks like markdown
        if any(marker in text for marker in ["##", "**", "---", "- "]):
            st.markdown(text)
        else:
            st.text(text)
    else:
        st.info("No content available for this memory entry.")


def _infer_selected_case() -> str | None:
    """Guess the active case_number from the current sidebar selection."""
    if st.session_state.selected_source == "memory" and st.session_state.selected_memory_key:
        prefix, _ = st.session_state.selected_memory_key
        _, case_id = _parse_prefix(prefix)
        return case_id or None
    if st.session_state.selected_source == "workspace" and st.session_state.selected_file:
        try:
            rel = st.session_state.selected_file.relative_to(WORKSPACE_DIR / "ocr_output")
            return rel.parts[0]
        except (ValueError, IndexError):
            return None
    return None


# ── Data loading (shared between sidebar and chat tab) ────────────────────────

ocr_dir = WORKSPACE_DIR / "ocr_output"
memories = load_db_memories()

# Workspace cases: { case_name: Path }
ws_cases: dict[str, Path] = {}
if ocr_dir.exists():
    for _item in sorted(ocr_dir.iterdir(), key=lambda p: p.name.lower()):
        if _item.is_dir():
            ws_cases[_item.name] = _item

# Memory cases: { case_name: [record, ...] } — exclude filesystem namespace
mem_cases: dict[str, list[dict]] = {}
for m in memories:
    ns_type, case_id = _parse_prefix(m["prefix"])
    if ns_type == "filesystem":
        continue
    label = case_id or m["prefix"]
    mem_cases.setdefault(label, []).append(m)

all_cases = sorted(set(ws_cases.keys()) | set(mem_cases.keys()))


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<div class="panel-heading">📂 Cases</div>', unsafe_allow_html=True)

    if not all_cases:
        st.info("No cases found.")
    else:
        for case_name in all_cases:
            with st.expander(f"📋 {case_name}", expanded=True):

                # ── input_files ──────────────────────────────────────────────
                if case_name in ws_cases:
                    with st.expander("📂 supporting docs", expanded=True):
                        _tree = load_workspace_tree(ws_cases[case_name])
                        if _tree:
                            render_tree(_tree)
                        else:
                            st.caption("No files.")

                # ── reports ──────────────────────────────────────────────────
                if case_name in mem_cases:
                    with st.expander("📊 reports", expanded=True):
                        for rec in sorted(
                            (
                                r for r in mem_cases[case_name]
                                if r["key"].lstrip("/") in ("report.md", "application_details.md")
                                or r["key"].lstrip("/").endswith("_findings.md")
                            ),
                            key=lambda r: r["key"],
                        ):
                            display = rec["key"].lstrip("/")
                            short = display if len(display) <= 32 else "…" + display[-29:]
                            mem_key = f"mem_{rec['prefix']}_{rec['key']}"
                            st.markdown('<div class="mem-link">', unsafe_allow_html=True)
                            if st.button(
                                f"🗒️ {short}",
                                key=mem_key,
                                use_container_width=True,
                                help=f"{rec['prefix']} › {rec['key']}",
                            ):
                                st.session_state.selected_memory_key = (rec["prefix"], rec["key"])
                                st.session_state.selected_source = "memory"
                                st.rerun()
                            st.markdown("</div>", unsafe_allow_html=True)


# ── Layout ───────────────────────────────────────────────────────────────────

# Header
st.markdown(
    f"""
    <div class="fionaa-header">
        <img src="data:image/png;base64,{_logo_b64}" style="height:40px;width:auto;" />
        <div>
            <h1>FIONAA</h1>
            <p>FInancial ONline loan Application Assistant</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_content, tab_chat = st.tabs(["📄 Content", "💬 Chat"])


# ── Content tab ───────────────────────────────────────────────────────────────

with tab_content:
    st.markdown('<div class="panel-heading">📄 Content</div>', unsafe_allow_html=True)

    if st.session_state.selected_source == "workspace" and st.session_state.selected_file:
        path = st.session_state.selected_file
        if path.exists():
            render_file_content(path)
        else:
            st.warning("File no longer exists.")

    elif st.session_state.selected_source == "memory" and st.session_state.selected_memory_key:
        sel = st.session_state.selected_memory_key  # (prefix, key) tuple
        record = next(
            (m for m in memories if (m["prefix"], m["key"]) == tuple(sel)),
            None,
        )
        if record:
            render_memory_content(record)
        else:
            st.warning("Memory record not found.")

    else:
        st.markdown(
            """
            <div style="text-align:center;padding:80px 20px;color:#90A4AE;">
                <div style="font-size:4rem;margin-bottom:16px;">🔵</div>
                <div style="font-size:1.1rem;font-weight:600;color:#1E88E5;">Welcome to Fionaa</div>
                <div style="font-size:0.9rem;margin-top:8px;">
                    Select a file from the sidebar to view.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── Chat tab ──────────────────────────────────────────────────────────────────

with tab_chat:
    st.markdown('<div class="panel-heading">💬 Chat</div>', unsafe_allow_html=True)

    if not all_cases:
        st.info("No cases found. Run the assessment pipeline first.")
    else:
        # Case selector — default to whatever is open in the Content tab
        inferred_case = _infer_selected_case()
        default_idx = all_cases.index(inferred_case) if inferred_case in all_cases else 0

        col_case, col_clear = st.columns([5, 1])
        with col_case:
            chat_case = st.selectbox(
                "Case",
                options=all_cases,
                index=default_idx,
                label_visibility="collapsed",
                key="chat_case_select",
            )
        with col_clear:
            if st.button("🗑️ Clear", use_container_width=True, help="Clear chat history for this case"):
                st.session_state.chat_messages.pop(chat_case, None)
                st.rerun()

        st.divider()

        # ── Chat history ──────────────────────────────────────────────────────
        case_msgs = st.session_state.chat_messages.get(chat_case, [])
        for msg in case_msgs:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # ── Chat input ────────────────────────────────────────────────────────
        if prompt := st.chat_input("Ask about this case…", key="chat_input"):
            # Append user message immediately
            if chat_case not in st.session_state.chat_messages:
                st.session_state.chat_messages[chat_case] = []
            st.session_state.chat_messages[chat_case].append(
                {"role": "user", "content": prompt}
            )

            # Show the user bubble straight away, then stream the response
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    graph = _get_chatbot()
                    thread_id = f"chatbot-{chat_case}"
                    result = _run_async(
                        graph.ainvoke(
                            {
                                "messages": [{"role": "user", "content": prompt}],
                                "case_number": chat_case,
                            },
                            config={"configurable": {"thread_id": thread_id, "case_number": chat_case}},
                        )
                    )

                ai_msg = result["messages"][-1]
                ai_content = (
                    ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)
                )
                st.markdown(ai_content)

            st.session_state.chat_messages[chat_case].append(
                {"role": "assistant", "content": ai_content}
            )
