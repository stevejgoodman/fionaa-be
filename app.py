"""Fionaa - File, Memory Viewer, and Chat application."""

import asyncio
import base64
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("fionaa")

# ── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent

# src/ on path — must be set before any src imports below
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import streamlit as st
from backends.gcs_backend import make_gcs_client
from helper import extract_chunk_image

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
        log.error("GCS list_cases failed: %s", exc)
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
    except Exception as exc:
        log.warning("GCS list_files failed for prefix=%s: %s", prefix, exc)
        return []


def _read_gcs_text(blob_name: str) -> str:
    """Download a GCS blob as UTF-8 text."""
    _, bucket = _gcs_bucket()
    return bucket.blob(blob_name).download_as_text(encoding="utf-8")


def _read_gcs_bytes(blob_name: str) -> bytes:
    """Download a GCS blob as raw bytes."""
    _, bucket = _gcs_bucket()
    return bucket.blob(blob_name).download_as_bytes()


_PDF_TEMP_DIR = Path(tempfile.gettempdir()) / "fionaa_pdf_cache"
_PDF_TEMP_DIR.mkdir(exist_ok=True)


@st.cache_data(ttl=3600)
def _get_local_pdf_path(blob_name: str) -> str | None:
    """Download a GCS PDF blob to a local temp file and return the path.

    Cached for 1 hour — PDFs don't change during a session.
    """
    import hashlib
    safe_name = hashlib.md5(blob_name.encode()).hexdigest() + ".pdf"
    local_path = _PDF_TEMP_DIR / safe_name
    if not local_path.exists():
        try:
            pdf_bytes = _read_gcs_bytes(blob_name)
            local_path.write_bytes(pdf_bytes)
        except Exception as exc:
            log.warning("Could not download PDF %s: %s", blob_name, exc)
            return None
    return str(local_path)


_VISUAL_REF_RE = re.compile(r"\[VISUAL_REF:([^\]]+)\]")


def _strip_visual_refs(text: str) -> str:
    """Remove all [VISUAL_REF:...] markers from *text*."""
    return _VISUAL_REF_RE.sub("", text).strip()


def _parse_visual_refs(text: str) -> list[dict]:
    """Extract all [VISUAL_REF:...] markers from *text* and return as dicts."""
    refs = []
    for payload in _VISUAL_REF_RE.findall(text):
        ref = {}
        for part in payload.split("|"):
            if "=" in part:
                k, v = part.split("=", 1)
                ref[k.strip()] = v.strip()
        if {"case", "doc", "page", "bbox"}.issubset(ref):
            refs.append(ref)
    return refs


def _render_visual_refs(text: str) -> None:
    """Render any [VISUAL_REF:...] markers in *text* as cropped PDF images."""
    refs = _parse_visual_refs(text)
    if not refs:
        return
    for ref in refs:
        try:
            blob_name = f"{ref['case']}/loan_application/{ref['doc']}"
            local_path = _get_local_pdf_path(blob_name)
            if local_path is None:
                continue
            page_num = int(ref["page"])
            bbox = [float(x) for x in ref["bbox"].split(",")]
            img_bytes = extract_chunk_image(
                pdf_path=local_path,
                page_num=page_num,
                bbox=bbox,
                highlight=True,
                padding=15,
            )
            if img_bytes:
                st.image(
                    img_bytes,
                    caption=f"Source: {ref['doc']} — page {page_num + 1}",
                    use_container_width=False,
                )
        except Exception as exc:
            log.warning("Failed to render visual ref %s: %s", ref, exc)


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
        log.info("Connecting to remote LangGraph at %s", langgraph_url)
        from langgraph.pregel.remote import RemoteGraph  # noqa: PLC0415
        graph = RemoteGraph(
            "chatbot",
            url=langgraph_url,
            api_key=os.environ.get("LANGSMITH_API_KEY"),
        )
        loop = asyncio.new_event_loop()
        threading.Thread(target=loop.run_forever, daemon=True).start()
        return loop, graph

    log.info("Building chatbot graph in-process")
    from chatbot_graph import build_chatbot_graph  # noqa: PLC0415
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    future = asyncio.run_coroutine_threadsafe(build_chatbot_graph(), loop)
    graph = future.result(timeout=120)
    log.info("Chatbot graph ready")
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
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* ── Global reset ─────────────────────────────────────────────────────── */
    #MainMenu { visibility: hidden; }
    .stDeployButton { display: none; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stHeader"] { display: none; }

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }

    /* ── App background ───────────────────────────────────────────────────── */
    .stApp {
        background-color: #F7F8FA;
    }

    /* ── Sticky header wrapper ────────────────────────────────────────────── */
    [data-testid="stMainBlockContainer"] > div:first-child {
        position: sticky;
        top: 0;
        z-index: 999;
        background: #F7F8FA;
        padding-bottom: 6px;
    }

    /* ── Header bar ───────────────────────────────────────────────────────── */
    .fionaa-header {
        background: #FFFFFF;
        border-bottom: 1px solid #E5E8ED;
        padding: 16px 28px;
        border-radius: 12px;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        gap: 14px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .fionaa-header-text h1 {
        margin: 0;
        font-size: 1.35rem;
        font-weight: 700;
        color: #111827;
        letter-spacing: -0.3px;
    }
    .fionaa-header-text p {
        margin: 2px 0 0;
        font-size: 0.78rem;
        color: #6B7280;
        font-weight: 400;
        letter-spacing: 0.1px;
    }
    .fionaa-header-badge {
        margin-left: auto;
        background: #EFF6FF;
        color: #1D4ED8;
        font-size: 0.7rem;
        font-weight: 600;
        padding: 4px 10px;
        border-radius: 20px;
        border: 1px solid #BFDBFE;
        letter-spacing: 0.4px;
    }

    /* ── Sidebar ──────────────────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background: #FFFFFF;
        border-right: 1px solid #E5E8ED;
    }
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        padding-top: 1.5rem;
    }

    /* ── Panel headings ───────────────────────────────────────────────────── */
    .panel-heading {
        color: #374151;
        padding: 0 0 10px 0;
        border-bottom: 2px solid #E5E8ED;
        font-weight: 600;
        font-size: 0.72rem;
        letter-spacing: 0.8px;
        margin-bottom: 14px;
        text-transform: uppercase;
    }

    /* ── Sidebar expanders — strip every border/bg Streamlit adds ────────── */
    [data-testid="stSidebar"] [data-testid="stExpander"],
    [data-testid="stSidebar"] [data-testid="stExpander"] > details,
    [data-testid="stSidebar"] details {
        border: none !important;
        border-radius: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        outline: none !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    [data-testid="stSidebar"] details > summary,
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        font-size: 0.73rem !important;
        font-weight: 600 !important;
        color: #374151 !important;
        padding: 5px 0 !important;
        background: transparent !important;
        border: none !important;
        border-bottom: 1px solid #E5E8ED !important;
        border-radius: 0 !important;
        margin-bottom: 2px !important;
        list-style: none;
    }
    [data-testid="stSidebar"] details > summary:hover {
        background: transparent !important;
        color: #1D4ED8 !important;
    }
    [data-testid="stSidebar"] details > summary::-webkit-details-marker { display: none; }
    [data-testid="stSidebar"] [data-testid="stExpanderDetails"],
    [data-testid="stSidebar"] details > div {
        padding: 0 !important;
        border: none !important;
        background: transparent !important;
    }

    /* ── Sidebar file tree buttons ────────────────────────────────────────── */
    [data-testid="stSidebar"] .stButton {
        margin: 0 !important;
        padding: 0 !important;
    }
    [data-testid="stSidebar"] .stButton > button,
    [data-testid="stSidebar"] [data-testid^="stBaseButton"] {
        text-align: left !important;
        background: #FFFFFF !important;
        border: none !important;
        border-color: transparent !important;
        box-shadow: none !important;
        outline: none !important;
        color: #4B5563;
        padding: 1px 0 2px !important;
        font-size: 0.72rem;
        font-weight: 400;
        border-radius: 0 !important;
        width: 100%;
        line-height: 1.35;
        min-height: unset !important;
        height: auto !important;
        transition: color 0.1s;
    }
    [data-testid="stSidebar"] .stButton > button:hover,
    [data-testid="stSidebar"] .stButton > button:focus,
    [data-testid="stSidebar"] [data-testid^="stBaseButton"]:hover,
    [data-testid="stSidebar"] [data-testid^="stBaseButton"]:focus {
        color: #1D4ED8 !important;
        background: #FFFFFF !important;
        border: none !important;
        border-color: transparent !important;
        box-shadow: none !important;
        outline: none !important;
        text-decoration: underline !important;
    }
    [data-testid="stSidebar"] .stButton > button:active,
    [data-testid="stSidebar"] [data-testid^="stBaseButton"]:active {
        color: #1E40AF !important;
        background: #FFFFFF !important;
    }

    /* ── Tabs ─────────────────────────────────────────────────────────────── */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        background: transparent;
        gap: 4px;
        border-bottom: 2px solid #E5E8ED;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        font-size: 0.82rem;
        font-weight: 500;
        color: #6B7280;
        padding: 8px 16px;
        border-radius: 6px 6px 0 0;
        background: transparent;
        border: none;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        color: #1D4ED8 !important;
        background: #EFF6FF !important;
        border-bottom: 2px solid #1D4ED8 !important;
    }

    /* ── Content card area ────────────────────────────────────────────────── */
    .content-card {
        background: #FFFFFF;
        border-radius: 10px;
        padding: 24px;
        border: 1px solid #E5E8ED;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        min-height: 500px;
    }

    /* ── Chat messages ────────────────────────────────────────────────────── */
    [data-testid="stChatMessage"] {
        background: #FFFFFF;
        border: 1px solid #E5E8ED;
        border-radius: 10px;
        padding: 12px 16px;
        margin-bottom: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }

    /* ── Chat input ───────────────────────────────────────────────────────── */
    [data-testid="stChatInput"] {
        border: 1px solid #D1D5DB !important;
        border-radius: 10px !important;
        background: #FFFFFF !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
    }
    [data-testid="stChatInput"]:focus-within {
        border-color: #1D4ED8 !important;
        box-shadow: 0 0 0 3px rgba(29,78,216,0.08) !important;
    }

    /* ── Selectbox ────────────────────────────────────────────────────────── */
    [data-testid="stSelectbox"] > div > div {
        border-color: #D1D5DB !important;
        border-radius: 8px !important;
        font-size: 0.82rem !important;
        background: #FFFFFF !important;
    }

    /* ── Divider ──────────────────────────────────────────────────────────── */
    hr {
        border-color: #E5E8ED !important;
        margin: 12px 0 !important;
    }

    /* ── Clear button ─────────────────────────────────────────────────────── */
    [data-testid="stButton"]:has(button[kind="secondary"]) button {
        border: 1px solid #E5E8ED !important;
        border-radius: 8px !important;
        font-size: 0.78rem !important;
        color: #6B7280 !important;
    }
    [data-testid="stButton"]:has(button[kind="secondary"]) button:hover {
        border-color: #FCA5A5 !important;
        color: #DC2626 !important;
        background: #FEF2F2 !important;
    }

    /* ── File icon accent colours ─────────────────────────────────────────── */
    .icon-pdf  { color: #DC2626; }
    .icon-img  { color: #7C3AED; }
    .icon-json { color: #D97706; }
    .icon-md   { color: #059669; }
    .icon-txt  { color: #6B7280; }
    .icon-dir  { color: #1D4ED8; }
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
    st.markdown('<div class="panel-heading">Cases</div>', unsafe_allow_html=True)

    if not all_cases:
        st.info("No cases found.")
    else:
        for case_name in all_cases:
            if case_name == "loan_policy_documents":
                continue
            with st.expander(case_name, expanded=True):

                # ── supporting docs (ocr_output) ─────────────────────────────
                ocr_files = _list_gcs_files(f"{case_name}/ocr_output")
                if ocr_files:
                    with st.expander("supporting docs", expanded=True):
                        for blob_name in ocr_files:
                            name = _blob_display_name(blob_name)
                            ext = Path(name).suffix.lower()
                            if ext not in RENDERABLE_EXTS or ext == ".json":
                                continue
                            if st.button(name, key=f"ocr_{blob_name}", use_container_width=True):
                                st.session_state.selected_file = blob_name
                                st.rerun()

                # ── reports ───────────────────────────────────────────────────
                report_files = _list_gcs_files(f"{case_name}/reports")
                if report_files:
                    with st.expander("reports", expanded=True):
                        for blob_name in report_files:
                            name = _blob_display_name(blob_name)
                            if Path(name).suffix.lower() == ".json":
                                continue
                            short = name if len(name) <= 32 else "…" + name[-29:]
                            if st.button(
                                short,
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
        <img src="data:image/png;base64,{_logo_b64}" style="height:36px;width:auto;border-radius:6px;" />
        <div class="fionaa-header-text">
            <h1>Fionaa</h1>
            <p>Financial Online Loan Application Assistant</p>
        </div>
        <span class="fionaa-header-badge">BETA</span>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_content, tab_chat = st.tabs(["📄 Content", "💬 Chat"])


# ── Content tab ───────────────────────────────────────────────────────────────

with tab_content:
    st.markdown('<div class="panel-heading">Content</div>', unsafe_allow_html=True)

    if st.session_state.selected_file:
        try:
            log.info("Rendering file: %s", st.session_state.selected_file)
            render_gcs_file_content(st.session_state.selected_file)
        except Exception as exc:
            log.error("Failed to render file %s: %s", st.session_state.selected_file, exc)
            st.warning(f"Could not load file: {exc}")
    else:
        st.markdown(
            """
            <div style="text-align:center;padding:100px 20px;color:#9CA3AF;">
                <div style="font-size:3rem;margin-bottom:20px;opacity:0.4;">📂</div>
                <div style="font-size:1rem;font-weight:600;color:#374151;margin-bottom:6px;">No file selected</div>
                <div style="font-size:0.82rem;color:#9CA3AF;">
                    Choose a case and file from the sidebar to get started.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── Chat tab ──────────────────────────────────────────────────────────────────

with tab_chat:
    st.markdown('<div class="panel-heading">Chat</div>', unsafe_allow_html=True)

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
                st.markdown(_strip_visual_refs(msg["content"]))
                if msg["role"] == "assistant":
                    _render_visual_refs(msg.get("visual_refs", ""))

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
                    log.info("Chat invoke case=%s thread=%s prompt_len=%d", chat_case, thread_id, len(prompt))
                    t0 = time.monotonic()
                    result = _run_async(
                        graph.ainvoke(
                            {
                                "messages": [{"role": "user", "content": prompt}],
                                "case_number": chat_case,
                            },
                            config={"configurable": {"thread_id": thread_id, "case_number": chat_case}},
                        )
                    )
                    log.info("Chat response case=%s elapsed=%.1fs", chat_case, time.monotonic() - t0)

                ai_msg = result["messages"][-1]
                # RemoteGraph returns messages as dicts; in-process graph returns
                # LangChain message objects.  Handle both.
                def _msg_type(m) -> str:
                    if isinstance(m, dict):
                        return m.get("type", m.get("role", ""))
                    return getattr(m, "type", "")

                def _msg_content(m) -> str:
                    c = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                    if isinstance(c, list):
                        return " ".join(
                            p.get("text", str(p)) if isinstance(p, dict) else str(p) for p in c
                        )
                    return c or ""

                ai_content = _msg_content(ai_msg) or str(ai_msg)
                st.markdown(_strip_visual_refs(ai_content))

                # Extract VISUAL_REF markers from tool messages in the current turn only.
                # result["messages"] is the full thread history (add_messages reducer),
                # so slice from the last human/user message to avoid re-rendering
                # refs from previous turns.
                all_msgs = result["messages"]
                log.info(
                    "Chat message types: %s",
                    [_msg_type(m) for m in all_msgs],
                )
                last_user_idx = max(
                    (i for i, m in enumerate(all_msgs) if _msg_type(m) in ("human", "user")),
                    default=0,
                )
                log.info(
                    "Chat last_user_idx=%d total=%d tool_after=%d",
                    last_user_idx, len(all_msgs),
                    sum(1 for m in all_msgs[last_user_idx:] if _msg_type(m) == "tool"),
                )
                tool_refs_text = "\n".join(
                    _msg_content(msg)
                    for msg in all_msgs[last_user_idx:]
                    if _msg_type(msg) == "tool" and _msg_content(msg)
                )
                # Also check the AI response itself — the prompt instructs the LLM
                # to copy [VISUAL_REF:...] markers through into its reply.
                combined_refs = "\n".join(filter(None, [tool_refs_text, ai_content]))
                _render_visual_refs(combined_refs)

            st.session_state.chat_messages[chat_case].append(
                {
                    "role": "assistant",
                    "content": ai_content,
                    "visual_refs": combined_refs,
                }
            )
