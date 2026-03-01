"""Gmail ingestion pipeline that triggers the Fionaa assessment graph directly.

Fetches emails from Gmail (filtered by address, recency, and read-status),
extracts PDF attachments, saves them for the assessment pipeline, and
invokes the Fionaa assessment graph for each email.

Usage
-----
    uv run python src/gmail/ingest.py --email inbox@yourdomain.com
    uv run python src/gmail/ingest.py --email inbox@yourdomain.com --minutes-since 60
    uv run python src/gmail/ingest.py --email inbox@yourdomain.com --include-read --early

Environment variables
---------------------
    BUCKET_NAME    GCS bucket for PDF storage  (optional — local-only if unset)
    GCP_PROJECT_ID GCP project ID              (optional — needed for GCS)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr

from dotenv import load_dotenv
from googleapiclient.discovery import build

from gmail.auth import load_gmail_credentials, setup_gcs_authentication
from gmail.extractor import extract_email_data, extract_pdf_attachments

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sender_dirname(from_header: str) -> str:
    """Derive a filesystem-safe directory name from a From header value.

    Extracts the display name (or email local-part if no display name) and
    removes all spaces and punctuation, leaving only alphanumeric characters.
    """
    display_name, addr = parseaddr(from_header)
    name = display_name.strip() or addr.split("@")[0]
    return re.sub(r"[^A-Za-z0-9]", "", name) or "unknown"


# ---------------------------------------------------------------------------
# Graph integration
# ---------------------------------------------------------------------------

_fionaa_cache: object = None


async def _get_graph():
    """Return the compiled Fionaa graph, building it on first call."""
    global _fionaa_cache
    if _fionaa_cache is None:
        from graph import build_graph  # noqa: PLC0415
        _fionaa_cache = await build_graph()
    return _fionaa_cache


async def ingest_email_to_graph(email_data: dict) -> dict:
    """Invoke the Fionaa assessment graph directly for a single email.

    Builds an ``email_input`` payload from *email_data* and passes it to the
    compiled graph.  The graph's ``startup_node`` derives ``case_number`` from
    the sender address and seeds the conversation with the email body
    (the applicant's loan application text).

    Args:
        email_data: Dict produced by :func:`~gmail.extractor.extract_email_data`,
                    optionally extended with a ``pdf_attachments`` key.

    Returns:
        Final graph state dict.
    """
    graph = await _get_graph()

    # case_number must match the directory where attachments were saved (data/<case_number>/)
    case_number = _sender_dirname(email_data["from_email"])
    email_input: dict = {
        "from": email_data["from_email"],
        "to": email_data["to_email"],
        "subject": email_data["subject"],
        "body": email_data["page_content"],
        "id": email_data["id"],
        "case_number": case_number,
    }
    if email_data.get("pdf_attachments"):
        email_input["pdf_attachments"] = email_data["pdf_attachments"]
        logger.info(
            "Attaching %d file path(s) to graph input",
            len(email_data["pdf_attachments"]),
        )

    thread_id = case_number
    config = {"configurable": {"thread_id": thread_id, "case_number": case_number}}

    logger.info("Invoking assessment graph — thread_id=%s", thread_id)
    result = await graph.ainvoke({"email_input": email_input}, config=config)
    logger.info("Graph execution complete — thread_id=%s", thread_id)
    return result


# ---------------------------------------------------------------------------
# Ingestion dataclass
# ---------------------------------------------------------------------------

@dataclass
class IngestConfig:
    """Configuration for a single ingestion run."""

    email: str
    """Gmail address to filter on (``to:`` or ``from:``)."""

    minutes_since: int = 0
    """Only fetch emails newer than this many minutes.  0 = no time filter."""

    include_read: bool = False
    """If *False* (default) only unread emails are fetched."""

    early_stop: bool = False
    """If *True* stop after processing the first email (useful for smoke-tests)."""

    dry_run: bool = False
    """If *True* download attachments but skip the graph invocation."""


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def fetch_and_process_emails(config: IngestConfig) -> int:
    """Fetch emails and route each one into the assessment pipeline.

    Args:
        config: Ingestion parameters.

    Returns:
        Number of emails successfully processed (0 on error).
    """
    # Ensure GCS credentials are available (non-fatal if they are not)
    setup_gcs_authentication()

    credentials = load_gmail_credentials()
    if not credentials:
        logger.error("Cannot proceed without Gmail credentials.")
        return 0

    service = build("gmail", "v1", credentials=credentials)

    # Build Gmail search query
    query_parts = [f"to:{config.email} OR from:{config.email}"]
    if config.minutes_since > 0:
        after_ts = int((datetime.now() - timedelta(minutes=config.minutes_since)).timestamp())
        query_parts.append(f"after:{after_ts}")
    if not config.include_read:
        query_parts.append("is:unread")

    query = " ".join(query_parts)
    logger.info("Gmail search query: %s", query)

    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])

    if not messages:
        logger.info("No emails matched the search query.")
        return 0

    logger.info("Found %d email(s)", len(messages))
    processed = 0

    for i, msg_stub in enumerate(messages):
        if config.early_stop and i > 0:
            logger.info("Early stop after %d email(s)", i)
            break

        message = (
            service.users()
            .messages()
            .get(userId="me", id=msg_stub["id"], format="full")
            .execute()
        )
        email_data = extract_email_data(message)

        logger.info(
            "Processing email %d/%d — from=%s subject=%s",
            i + 1,
            len(messages),
            email_data["from_email"],
            email_data["subject"],
        )

        # Derive case_number from sender display name so files land in data/<name>/
        case_number = _sender_dirname(email_data["from_email"])

        pdf_attachments = extract_pdf_attachments(
            service,
            msg_stub["id"],
            message["payload"],
            case_number=case_number,
        )

        if pdf_attachments:
            email_data["pdf_attachments"] = [att["filepath"] for att in pdf_attachments]
            logger.info("Extracted %d attachment(s)", len(pdf_attachments))
        else:
            email_data["pdf_attachments"] = []
            logger.info("No attachments found")

        if not config.dry_run:
            try:
                await ingest_email_to_graph(email_data)
                processed += 1
            except Exception as exc:
                logger.error("Graph execution failed for email %s: %s", msg_stub["id"], exc)
        else:
            logger.info("Dry-run: skipping graph invocation")
            processed += 1

    logger.info("Done — processed %d/%d email(s)", processed, len(messages))
    return processed


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fionaa Gmail ingest — fetch emails and route to assessment pipeline"
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Gmail address to filter on (to: or from: this address)",
    )
    parser.add_argument(
        "--minutes-since",
        type=int,
        default=0,
        metavar="N",
        help="Only fetch emails from the last N minutes (default: no time filter)",
    )
    parser.add_argument(
        "--include-read",
        action="store_true",
        help="Include read emails (default: unread only)",
    )
    parser.add_argument(
        "--early",
        action="store_true",
        help="Stop after processing the first matching email",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download attachments but skip the graph invocation",
    )
    return parser


async def _main() -> None:
    args = _build_parser().parse_args()
    config = IngestConfig(
        email=args.email,
        minutes_since=args.minutes_since,
        include_read=args.include_read,
        early_stop=args.early,
        dry_run=args.dry_run,
    )
    count = await fetch_and_process_emails(config)
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    asyncio.run(_main())
