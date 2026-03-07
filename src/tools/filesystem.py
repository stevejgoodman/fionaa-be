"""Read-only GCS tool for agent access to workspace files."""

from langchain.tools import tool

from backends.gcs_backend import GCSBackend

# Shared backend instance — reads BUCKET_NAME / GOOGLE_CLOUD_PROJECT from env
_gcs = GCSBackend()


@tool
def read_external_file(path: str) -> str:
    """Read a file from the GCS workspace.

    Pass a path relative to the /disk-files/ root, e.g.
    ``loan_policy_documents/asset-finance.md`` or
    ``<case_number>/ocr_output/bs_012025_extraction.json``.

    If the path resolves to a directory, returns a listing of objects inside it.
    """
    clean_path = "/" + (path or "").lstrip("/")

    # If it looks like a directory (no extension or trailing slash), list it
    info = _gcs.ls_info(clean_path)
    if info:
        # ls_info returns results only when path is a valid prefix/directory
        # Check whether clean_path itself is a blob (file)
        files = [e for e in info if not e.get("is_dir")]
        dirs = [e for e in info if e.get("is_dir")]
        if files or dirs:
            names = [e["path"] for e in sorted(info, key=lambda x: x["path"])]
            return "Directory — pass a file path. Contents:\n" + "\n".join(names)

    return _gcs.read(clean_path)
