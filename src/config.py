"""Project-wide paths and configuration constants."""

import os
from pathlib import Path

# Project root is two levels above this file (src/config.py -> src/ -> project root)
PROJECT_ROOT = Path(__file__).parent.parent

# Data directories
DATA_DIR = PROJECT_ROOT / "data"

# Workspace: agent's working directory (loan policy docs, OCR output, etc.)
WORKSPACE = DATA_DIR / "workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)

# Sub-directories within workspace
LOAN_POLICY_DIR = WORKSPACE / "loan_policy_documents"
OCR_OUTPUT_DIR = WORKSPACE / "ocr_output"

LOAN_POLICY_DIR.mkdir(parents=True, exist_ok=True)
OCR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# PostgreSQL / PGVectorStore config
PG_USER     = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_HOST     = os.getenv("PG_HOST", "localhost")
PG_PORT     = os.getenv("PG_PORT", "5432")
PG_DB       = os.getenv("PG_DB", "langchain")
PG_TABLE    = os.getenv("PG_TABLE", "ade_documents")
VECTOR_SIZE = 1536
EMBEDDING_MODEL = "text-embedding-3-small"
