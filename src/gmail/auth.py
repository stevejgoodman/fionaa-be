"""Authentication helpers for Gmail and Google Cloud Storage.

Credential lookup order
-----------------------
Gmail (OAuth 2.0):
    1. ``GMAIL_TOKEN`` environment variable (JSON string)
    2. ``.secrets/token.json`` file in the project root

    Re-run ``uv run python src/gcp/setup_gmail.py`` to refresh an expired token.

GCS (service account):
    1. ``GOOGLE_APPLICATION_CREDENTIALS`` environment variable
    2. ``.secrets/fionaa-service-acct.json`` in the project root
    3. Application Default Credentials (requires ``gcloud auth application-default login``)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

# Project root is three levels above src/gmail/auth.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SECRETS_DIR = _PROJECT_ROOT / ".secrets"
TOKEN_PATH = _SECRETS_DIR / "token.json"

_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]


def load_gmail_credentials() -> Credentials | None:
    """Load Gmail OAuth 2.0 credentials.

    Returns:
        A :class:`~google.oauth2.credentials.Credentials` object, or *None*
        if no valid token data can be found.
    """
    token_data: dict | None = None

    # 1. Try GMAIL_TOKEN env var (useful in containerised / CI environments)
    raw = os.getenv("GMAIL_TOKEN", "").strip()
    if raw:
        try:
            token_data = json.loads(raw)
            logger.info("Loaded Gmail credentials from GMAIL_TOKEN env var")
        except json.JSONDecodeError as exc:
            logger.warning("Could not parse GMAIL_TOKEN env var: %s", exc)

    # 2. Fall back to token.json on disk
    if token_data is None:
        if TOKEN_PATH.exists():
            try:
                token_data = json.loads(TOKEN_PATH.read_text())
                logger.info("Loaded Gmail credentials from %s", TOKEN_PATH)
            except Exception as exc:
                logger.warning("Could not read %s: %s", TOKEN_PATH, exc)
        else:
            logger.warning("Gmail token file not found at %s", TOKEN_PATH)

    if token_data is None:
        logger.error(
            "No Gmail credentials found. "
            "Run `uv run python src/gcp/setup_gmail.py` to authenticate."
        )
        return None

    try:
        return Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", _GMAIL_SCOPES),
        )
    except Exception as exc:
        logger.error("Failed to build Credentials object: %s", exc)
        return None


def setup_gcs_authentication() -> bool:
    """Ensure ``GOOGLE_APPLICATION_CREDENTIALS`` is configured for GCS access.

    Tries multiple sources in order:

    1. ``GOOGLE_APPLICATION_CREDENTIALS`` is already set and the file exists.
    2. ``.secrets/fionaa-service-acct.json`` in the project root.
    3. Application Default Credentials (ADC) via ``google.auth.default()``.

    Returns:
        ``True`` if any authentication method succeeded, ``False`` otherwise.
    """
    # 1. Existing env var
    existing = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if existing and Path(existing).is_file():
        logger.info("GCS auth: using GOOGLE_APPLICATION_CREDENTIALS=%s", existing)
        return True

    # 2. Well-known service account file in .secrets/
    sa_path = _SECRETS_DIR / "fionaa-service-acct.json"
    if sa_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_path)
        logger.info("GCS auth: found service account at %s", sa_path)
        return True

    # 3. Application Default Credentials
    try:
        from google.auth import default as _gauth_default

        _, project = _gauth_default()
        logger.info("GCS auth: using Application Default Credentials (project=%s)", project)
        return True
    except Exception as exc:
        logger.error(
            "GCS auth failed — no valid credentials found: %s. "
            "Set GOOGLE_APPLICATION_CREDENTIALS or run "
            "`gcloud auth application-default login`.",
            exc,
        )
        return False
