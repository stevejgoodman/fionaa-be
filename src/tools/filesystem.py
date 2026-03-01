"""Read-only filesystem tool for agent access to workspace files."""

from pathlib import Path

from langchain.tools import tool

from config import WORKSPACE


def is_allowed(path: Path) -> bool:
    """Return True if *path* is within the allowed workspace tree."""
    return str(path.resolve()).startswith(str(WORKSPACE.resolve()))


@tool
def read_external_file(path: str) -> str:
    """Read a readonly file from the workspace directory.

    Pass a path relative to the workspace root, e.g.
    ``loan_policy_documents/asset-finance.md`` or
    ``ocr_output/case@example.com/bs_012025_extraction.json``.

    If the path resolves to a directory, returns a list of files inside it.
    """
    clean_path = (path or "").lstrip("/")
    file_path = (WORKSPACE / clean_path).resolve()

    # Guide the agent if it asks for the workspace root itself
    if clean_path in ("", ".") or file_path == WORKSPACE.resolve():
        dirs = sorted(p.name for p in WORKSPACE.iterdir() if p.is_dir())
        return (
            "Workspace root — pass a sub-path to read a file. "
            "Available directories: " + ", ".join(dirs)
        )

    if not is_allowed(file_path):
        raise PermissionError(f"Access denied: {file_path}")

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if file_path.is_dir():
        names = sorted(f.name for f in file_path.iterdir() if f.is_file())
        return "Directory — pass a file path. Available files: " + ", ".join(names)

    return file_path.read_text(encoding="utf-8")
