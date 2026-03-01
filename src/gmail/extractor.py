"""Gmail message parsing and attachment extraction (PDF and JPEG).

Attachment storage strategy
----------------------------
Attachments are written to::

    <DATA_DIR>/<sender_email>/<filename>

where ``sender_email`` doubles as the **case number** expected by the
assessment pipeline (``graph.startup_node`` reads from ``data/<case_number>/``).

If ``BUCKET_NAME`` is set in the environment the file is also uploaded to GCS at::

    gs://<BUCKET_NAME>/<sender_email>/<filename>

and the returned filepath is the public HTTPS URL; otherwise it is the
local absolute path.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Project root is three levels above src/gmail/extractor.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _PROJECT_ROOT / "data"

BUCKET_NAME: str = os.getenv("BUCKET_NAME", "")
PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")


# ---------------------------------------------------------------------------
# Message body parsing
# ---------------------------------------------------------------------------

def extract_message_part(payload: dict) -> str:
    """Recursively extract plain-text (or HTML) body from a Gmail message payload.

    Preference order: ``text/plain`` → ``text/html`` → first nested part with content.

    Args:
        payload: Gmail API message payload dict.

    Returns:
        Decoded text content, or an empty string if nothing is found.
    """
    parts = payload.get("parts", [])

    if parts:
        # Prefer plain text
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8")

        # Fall back to HTML
        for part in parts:
            if part.get("mimeType") == "text/html":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8")

        # Recurse into nested multipart
        for part in parts:
            content = extract_message_part(part)
            if content:
                return content

    # Non-multipart body
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8")

    return ""


def extract_email_data(message: dict) -> dict:
    """Extract key metadata and body text from a full Gmail message object.

    Args:
        message: Full Gmail API message dict (retrieved with ``format='full'``).

    Returns:
        Dict with keys: ``from_email``, ``to_email``, ``subject``,
        ``page_content``, ``id``, ``thread_id``, ``send_time``.
    """
    headers = message["payload"]["headers"]

    def _header(name: str, default: str = "") -> str:
        return next((h["value"] for h in headers if h["name"] == name), default)

    return {
        "from_email": _header("From", "Unknown Sender"),
        "to_email": _header("To", "Unknown Recipient"),
        "subject": _header("Subject", "No Subject"),
        "page_content": extract_message_part(message["payload"]),
        "id": message["id"],
        "thread_id": message["threadId"],
        "send_time": _header("Date", "Unknown Date"),
    }


# ---------------------------------------------------------------------------
# Attachment extraction (PDF + JPEG)
# ---------------------------------------------------------------------------

_SUPPORTED_MIME_TYPES: dict[str, str] = {
    "application/pdf": "unnamed.pdf",
    "image/jpeg": "unnamed.jpg",
    "image/jpg": "unnamed.jpg",
}


def _find_attachment_parts(payload: dict) -> list[dict]:
    """Recursively collect all supported attachment descriptors from a message payload.

    Supported types: PDF (``application/pdf``) and JPEG (``image/jpeg``, ``image/jpg``).

    Args:
        payload: Gmail API message payload (or sub-part) dict.

    Returns:
        List of dicts with keys ``attachment_id``, ``filename``, ``mime_type``, ``size``.
    """
    results: list[dict] = []

    mime_type = payload.get("mimeType", "")
    if mime_type in _SUPPORTED_MIME_TYPES:
        attachment_id = payload.get("body", {}).get("attachmentId")
        filename = payload.get("filename") or _SUPPORTED_MIME_TYPES[mime_type]
        if attachment_id:
            results.append(
                {
                    "attachment_id": attachment_id,
                    "filename": filename,
                    "mime_type": mime_type,
                    "size": payload.get("body", {}).get("size", 0),
                }
            )
            logger.debug("Found attachment: %s (%s)", filename, mime_type)
        else:
            logger.warning("Attachment part has no attachmentId: %s", filename)

    for sub in payload.get("parts", []):
        results.extend(_find_attachment_parts(sub))

    return results


def _upload_to_gcs(data: bytes, blob_name: str, content_type: str = "application/octet-stream") -> str:
    """Upload *data* to GCS and return the public HTTPS URL.

    Args:
        data:         Raw file bytes.
        blob_name:    Object path within the bucket (e.g. ``case/file.pdf``).
        content_type: MIME type for the uploaded object.

    Returns:
        Public HTTPS URL of the uploaded object.

    Raises:
        google.cloud.exceptions.GoogleCloudError: on upload failure.
    """
    from google.cloud import storage as gcs

    client = gcs.Client(project=PROJECT_ID or None)
    bucket = client.bucket(BUCKET_NAME)

    # Avoid silently overwriting — append a counter if the object already exists
    base_blob_name = blob_name
    counter = 1
    while bucket.blob(blob_name).exists():
        stem = Path(base_blob_name).stem
        suffix = Path(base_blob_name).suffix
        parent = str(Path(base_blob_name).parent)
        blob_name = f"{parent}/{stem}_{counter}{suffix}"
        counter += 1

    blob = bucket.blob(blob_name)
    blob.upload_from_string(data, content_type=content_type)
    url = f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
    logger.info("Uploaded attachment to GCS: %s", url)
    return url


def extract_pdf_attachments(
    service: Any,
    message_id: str,
    payload: dict,
    case_number: str,
) -> list[dict]:
    """Download PDF and JPEG attachments and persist them for the assessment pipeline.

    Each file is saved to ``<DATA_DIR>/<case_number>/<filename>``.  If
    ``BUCKET_NAME`` is set the file is also uploaded to GCS and the returned
    filepath is the GCS HTTPS URL; otherwise it is the local absolute path.

    Args:
        service:      Authenticated Gmail API service resource.
        message_id:   Gmail message ID that carries the attachments.
        payload:      Gmail message payload dict.
        case_number:  Case identifier (typically the sender's email address).
                      Used as both the sub-directory name and the GCS prefix.

    Returns:
        List of dicts, one per successfully processed attachment, with keys:
        ``filename``, ``filepath`` (local path or GCS URL), ``size``.
    """
    attachment_parts = _find_attachment_parts(payload)
    if not attachment_parts:
        return []

    # Destination directory on disk
    case_dir = DATA_DIR / case_number
    case_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for part in attachment_parts:
        attachment_id = part["attachment_id"]
        filename = part["filename"]
        mime_type = part["mime_type"]

        logger.info("Downloading attachment: %s (%s, id=%s)", filename, mime_type, attachment_id)
        try:
            raw = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            file_bytes = base64.urlsafe_b64decode(raw["data"])
            if not file_bytes:
                logger.warning("Empty attachment data for %s — skipping", filename)
                continue

            # Always write locally (used by the assessment pipeline)
            local_path = case_dir / filename
            local_path.write_bytes(file_bytes)
            logger.info("Saved attachment locally: %s (%d bytes)", local_path, len(file_bytes))

            filepath: str = str(local_path)

            # Optionally upload to GCS
            if BUCKET_NAME:
                try:
                    blob_name = f"{case_number}/{filename}"
                    filepath = _upload_to_gcs(file_bytes, blob_name, content_type=mime_type)
                except Exception as gcs_exc:
                    logger.warning(
                        "GCS upload failed for %s (%s) — using local path",
                        filename,
                        gcs_exc,
                    )

            results.append({"filename": filename, "filepath": filepath, "size": len(file_bytes)})

        except Exception as exc:
            logger.error("Failed to extract attachment %s: %s", filename, exc, exc_info=True)

    return results
