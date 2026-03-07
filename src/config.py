"""Project-wide paths and configuration constants."""

from pathlib import Path

# Project root is two levels above this file (src/config.py -> src/ -> project root)
PROJECT_ROOT = Path(__file__).parent.parent

# Local staging directory — source documents land here before being uploaded to GCS
DATA_DIR = PROJECT_ROOT / "data"

# ---------------------------------------------------------------------------
# GCS virtual path prefixes (relative to the /disk-files/ backend root)
# ---------------------------------------------------------------------------
# Per-case layout under /disk-files/<case_number>/:
#   ocr_output/      — Landing AI extraction JSON and annotated PNGs
#   loan_application/ — original uploaded documents (PDF, etc.)
# Shared (not case-specific):
#   loan_policy_documents/ — lender policy markdown files

GCS_OCR_OUTPUT_PREFIX = "ocr_output"
GCS_LOAN_APPLICATION_PREFIX = "loan_application"
GCS_LOAN_POLICY_PREFIX = "loan_policy_documents"

# ---------------------------------------------------------------------------
# Vector / embedding config
# ---------------------------------------------------------------------------
VECTOR_SIZE = 1536
EMBEDDING_MODEL = "text-embedding-3-small"
