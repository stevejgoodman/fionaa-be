"""Fionaa - File, Memory Viewer, and Chat application."""

import asyncio
import base64
import json
import os
import sys
import threading
import uuid
from pathlib import Path
from  dotenv import load_dotenv
load_dotenv()

# ── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent

# src/ on path — must be set before any src imports below
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import streamlit as st
from backends.gcs_backend import make_gcs_client

_logo_b64 = base64.b64encode((PROJECT_ROOT / "logo.png").read_bytes()).decode()

RENDERABLE_EXTS = {".txt", ".md", ".json", ".pdf", ".jpg", ".jpeg", ".png"}


# ── GCS helpers ──────────────────────────────────────────────────────────────


def _gcs_bucket():
    bucket_name = os.environ["BUCKET_NAME"]
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    client = make_gcs_client(project=project)
    return client, client.bucket(bucket_name)


@st.cache_data(ttl=60)
def _list_gcs_cases() -> list[str]:
    """List all top-level case prefixes in the GCS bucket."""
    try:
        bucket_name = os.environ["BUCKET_NAME"]
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        client = make_gcs_client(project=project)
        blobs = client.list_blobs(bucket_name, delimiter="/")
        list(blobs)  # consume iterator to populate prefixes
        return sorted(prefix.rstrip("/") for prefix in (blobs.prefixes or []))
    except Exception as exc:
        st.sidebar.warning(f"GCS unavailable: {exc}")
        return []


@st.cache_data(ttl=60)
def _list_gcs_files(prefix: str) -> list[str]:
    """List all blob names directly under *prefix* (non-recursive)."""
    try:
        bucket_name = os.environ["BUCKET_NAME"]
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        client = make_gcs_client(project=project)
        gcs_prefix = prefix.strip("/") + "/"
        blobs = client.list_blobs(bucket_name, prefix=gcs_prefix, delimiter="/")
        return sorted(
            blob.name for blob in blobs if not blob.name.endswith("/")
        )
    except Exception:
        return []


def _read_gcs_text(blob_name: str) -> str:
    """Download a GCS blob as UTF-8 text."""
    _, bucket = _gcs_bucket()
    return bucket.blob(blob_name).download_as_text(encoding="utf-8")


def _read_gcs_bytes(blob_name: str) -> bytes:
    """Download a GCS blob as raw bytes."""
    _, bucket = _gcs_bucket()
    return bucket.blob(blob_name).download_as_bytes()


def _blob_display_name(blob_name: str) -> str:
    return blob_name.rstrip("/").split("/")[-1]


def _blob_ext(blob_name: str) -> str:
    return Path(_blob_display_name(blob_name)).suffix.lower()


def file_icon(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {
        ".pdf": "📄",
        ".jpg": "🖼️",
        ".jpeg": "🖼️",
        ".png": "🖼️",
        ".json": "📋",
        ".md": "📝",
        ".txt": "🗒️",
    }.get(ext, "📎")


# ── Persistent async event loop + chatbot graph ───────────────────────────────
# Streamlit is synchronous; the chatbot graph is async.
#
# The loop and the graph are cached TOGETHER as a single @st.cache_resource so
# they are always the same pair.  If they were separate, Streamlit script
# reloads would recreate the module-level loop while keeping the old cached
# graph, causing event loop affinity errors.


@st.cache_resource
def _get_loop_and_chatbot():
    """Return a (loop, graph) pair for the chatbot.

    When ``LANGGRAPH_URL`` is set the chatbot graph is accessed via the
    LangGraph Cloud API (``RemoteGraph``).  Otherwise the graph is built
    in-process so the app works standalone without a cloud deployment.
    """
    langgraph_url = os.environ.get("LANGGRAPH_URL", "").strip()
    if langgraph_url:
        from langgraph.pregel.remote import RemoteGraph  # noqa: PLC0415
        graph = RemoteGraph(
            "chatbot",
            url=langgraph_url,
            api_key=os.environ.get("LANGSMITH_API_KEY"),
        )
        # RemoteGraph is synchronous-friendly; wrap in a trivial loop so the
        # rest of the app can keep using _run_async unchanged.
        loop = asyncio.new_event_loop()
        threading.Thread(target=loop.run_forever, daemon=True).start()
        return loop, graph

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
    st.session_state.selected_file = None  # GCS blob name string
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = {}  # {case_number: [{"role": ..., "content": ...}]}


# ── Helpers ──────────────────────────────────────────────────────────────────


def render_gcs_file_content(blob_name: str) -> None:
    """Render a GCS file in the main pane."""
    ext = _blob_ext(blob_name)
    st.markdown(
        f"<div style='font-size:0.78rem;color:#546E7A;margin-bottom:8px'>"
        f"📂 {blob_name}</div>",
        unsafe_allow_html=True,
    )

    if ext in (".jpg", ".jpeg", ".png"):
        data = _read_gcs_bytes(blob_name)
        st.image(data, use_container_width=True)

    elif ext == ".pdf":
        data = _read_gcs_bytes(blob_name)
        b64 = base64.b64encode(data).decode()
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'width="100%" height="700" style="border:none;border-radius:8px;"></iframe>',
            unsafe_allow_html=True,
        )

    elif ext == ".md":
        st.markdown(_read_gcs_text(blob_name))

    elif ext == ".json":
        text = _read_gcs_text(blob_name)
        try:
            st.json(json.loads(text))
        except json.JSONDecodeError:
            st.code(text, language="json")

    else:  # .txt and anything else
        st.text(_read_gcs_text(blob_name))


def _infer_selected_case() -> str | None:
    """Guess the active case_number from the currently selected file."""
    if st.session_state.selected_file:
        parts = st.session_state.selected_file.split("/")
        return parts[0] if parts else None
    return None


# ── Data loading ──────────────────────────────────────────────────────────────

all_cases = _list_gcs_cases()


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<div class="panel-heading">📂 Cases</div>', unsafe_allow_html=True)

    if not all_cases:
        st.info("No cases found.")
    else:
        for case_name in all_cases:
            with st.expander(f"📋 {case_name}", expanded=True):

                # ── supporting docs (ocr_output) ─────────────────────────────
                ocr_files = _list_gcs_files(f"{case_name}/ocr_output")
                if ocr_files:
                    with st.expander("📂 supporting docs", expanded=True):
                        for blob_name in ocr_files:
                            name = _blob_display_name(blob_name)
                            if Path(name).suffix.lower() not in RENDERABLE_EXTS:
                                continue
                            label = f"{file_icon(name)} {name}"
                            if st.button(label, key=f"ocr_{blob_name}", use_container_width=True):
                                st.session_state.selected_file = blob_name
                                st.rerun()

                # ── reports ───────────────────────────────────────────────────
                report_files = _list_gcs_files(f"{case_name}/reports")
                if report_files:
                    with st.expander("📊 reports", expanded=True):
                        for blob_name in report_files:
                            name = _blob_display_name(blob_name)
                            short = name if len(name) <= 32 else "…" + name[-29:]
                            if st.button(
                                f"🗒️ {short}",
                                key=f"rep_{blob_name}",
                                use_container_width=True,
                                help=blob_name,
                            ):
                                st.session_state.selected_file = blob_name
                                st.rerun()


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

    if st.session_state.selected_file:
        try:
            render_gcs_file_content(st.session_state.selected_file)
        except Exception as exc:
            st.warning(f"Could not load file: {exc}")
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
                    thread_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"chatbot-{chat_case}"))
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
