"""Gmail ingestion package for Fionaa.

Fetches emails (with PDF attachments) and routes them into the assessment pipeline.

Typical entry point::

    uv run python src/gmail/ingest.py --email inbox@yourdomain.com
"""
