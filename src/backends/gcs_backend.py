"""GCSBackend: Read and write files in a Google Cloud Storage bucket."""

from __future__ import annotations

import fnmatch
import json
import os
import re
from datetime import UTC, datetime

from google.cloud import storage
from google.cloud.exceptions import NotFound
from google.oauth2 import service_account


def setup_google_credentials() -> None:
    """Ensure ``GOOGLE_APPLICATION_CREDENTIALS`` is set for IAM and GCS auth.

    If ``GOOGLE_APPLICATION_CREDENTIALS`` is already set (and the file exists)
    this is a no-op.  Otherwise, if ``GOOGLE_CREDENTIALS_JSON`` is set, the
    service account JSON is written to a temporary file (kept for the process
    lifetime) and ``GOOGLE_APPLICATION_CREDENTIALS`` is pointed at it.

    Call this once at process start — before any Google API clients are
    constructed — so that libraries that read ``GOOGLE_APPLICATION_CREDENTIALS``
    (e.g. ``google.oauth2.id_token.fetch_id_token``) find valid credentials.
    """
    import tempfile

    existing = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if existing and os.path.isfile(existing):
        return  # already configured

    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not creds_json:
        return

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="gcp_sa_"
    ) as f:
        f.write(creds_json)
        tmp_path = f.name

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp_path


def make_gcs_client(project: str | None = None) -> storage.Client:
    """Create a :class:`~google.cloud.storage.Client` using available credentials.

    Credential lookup order:
    1. ``GOOGLE_CREDENTIALS_JSON`` env var — service account JSON as a string.
       Useful for cloud deployments (e.g. LangGraph Cloud) where credential
       files cannot be placed on disk.
    2. Standard Google auth (``GOOGLE_APPLICATION_CREDENTIALS``, ADC, etc.).
    """
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if creds_json:
        info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(info)
        return storage.Client(project=project, credentials=credentials)
    return storage.Client(project=project)

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)
from deepagents.backends.utils import (
    check_empty_content,
    format_content_with_line_numbers,
    perform_string_replacement,
)


class GCSBackend(BackendProtocol):
    """Backend that reads and writes files in a Google Cloud Storage bucket.

    Paths are virtual and absolute (e.g. ``/ocr_output/case/file.json``).
    The leading ``/`` is stripped to form the GCS object key.

    Args:
        bucket_name: GCS bucket name. Defaults to ``BUCKET_NAME`` env var.
        project: GCP project ID. Defaults to ``GOOGLE_CLOUD_PROJECT`` env var.
        prefix: Optional key prefix prepended to every path (no leading slash).
    """

    def __init__(
        self,
        bucket_name: str | None = None,
        project: str | None = None,
        prefix: str = "",
    ) -> None:
        self._bucket_name = bucket_name or os.environ["BUCKET_NAME"]
        self._project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self._prefix = prefix.strip("/")

        self._client = make_gcs_client(project=self._project)
        self._bucket = self._client.bucket(self._bucket_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_key(self, virtual_path: str) -> str:
        """Convert a virtual absolute path to a GCS object key."""
        stripped = virtual_path.lstrip("/")
        return f"{self._prefix}/{stripped}" if self._prefix else stripped

    def _to_virtual(self, key: str) -> str:
        """Convert a GCS object key back to a virtual absolute path."""
        if self._prefix and key.startswith(self._prefix + "/"):
            key = key[len(self._prefix) + 1:]
        return "/" + key

    def _blob_info(self, blob: storage.Blob) -> FileInfo:
        info: FileInfo = {"path": self._to_virtual(blob.name), "is_dir": False}
        if blob.size is not None:
            info["size"] = blob.size
        if blob.updated:
            info["modified_at"] = blob.updated.isoformat()
        return info

    # ------------------------------------------------------------------
    # BackendProtocol implementation
    # ------------------------------------------------------------------

    def ls_info(self, path: str) -> list[FileInfo]:
        """List objects and virtual directories directly under *path* (non-recursive)."""
        prefix = self._to_key(path)
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        blobs = self._client.list_blobs(
            self._bucket_name, prefix=prefix, delimiter="/"
        )
        results: list[FileInfo] = []

        for blob in blobs:
            results.append(self._blob_info(blob))

        # Synthetic directory entries from common prefixes
        for cp in blobs.prefixes:  # type: ignore[attr-defined]
            virt = self._to_virtual(cp.rstrip("/")) + "/"
            results.append({"path": virt, "is_dir": True})

        results.sort(key=lambda x: x["path"])
        return results

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Download and return file content with line numbers.

        If *file_path* resolves to a virtual directory (no blob by that exact
        name but child blobs exist), returns a directory listing instead.
        """
        # Bare/root paths are always directories
        normalised = file_path if file_path not in ("", ".", "/.", "./") else "/"
        key = self._to_key(normalised)

        # Empty key or explicit trailing slash → directory, skip blob attempt
        if not key or key.endswith("/"):
            return self._directory_listing(normalised)

        blob = self._bucket.blob(key)
        try:
            content = blob.download_as_text(encoding="utf-8")
        except NotFound:
            listing = self._directory_listing(normalised)
            if listing.startswith("Directory"):
                return listing
            return f"Error: File '{file_path}' not found"
        except Exception:
            # 400 / other errors often mean the key is a prefix, not a blob
            listing = self._directory_listing(normalised)
            if listing.startswith("Directory"):
                return listing
            return f"Error: File '{file_path}' not found"

        empty_msg = check_empty_content(content)
        if empty_msg:
            return empty_msg

        lines = content.splitlines()
        if offset >= len(lines):
            return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

        selected = lines[offset: offset + limit]
        return format_content_with_line_numbers(selected, start_line=offset + 1)

    def _directory_listing(self, path: str) -> str:
        entries = self.ls_info(path)
        if not entries:
            return f"Error: File '{path}' not found"
        names = [e["path"] for e in entries]
        return "Directory listing:\n" + "\n".join(names)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Create a new object; returns an error if it already exists."""
        key = self._to_key(file_path)
        blob = self._bucket.blob(key)
        if blob.exists():
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                      "Read and then make an edit, or write to a new path."
            )
        try:
            blob.upload_from_string(content, content_type="text/plain; charset=utf-8")
        except Exception as exc:
            return WriteResult(error=f"Error writing file '{file_path}': {exc}")
        return WriteResult(path=file_path, files_update=None)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Read → replace → upload."""
        key = self._to_key(file_path)
        blob = self._bucket.blob(key)
        try:
            content = blob.download_as_text(encoding="utf-8")
        except NotFound:
            return EditResult(error=f"Error: File '{file_path}' not found")
        except Exception as exc:
            return EditResult(error=f"Error reading file '{file_path}': {exc}")

        result = perform_string_replacement(content, old_string, new_string, replace_all)
        if isinstance(result, str):
            return EditResult(error=result)

        new_content, occurrences = result
        try:
            blob.upload_from_string(
                new_content, content_type="text/plain; charset=utf-8"
            )
        except Exception as exc:
            return EditResult(error=f"Error writing file '{file_path}': {exc}")
        return EditResult(path=file_path, files_update=None, occurrences=int(occurrences))

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Return objects under *path* whose virtual path matches *pattern*."""
        prefix = self._to_key(path)
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        blobs = self._client.list_blobs(self._bucket_name, prefix=prefix or None)
        results: list[FileInfo] = []
        for blob in blobs:
            virt = self._to_virtual(blob.name)
            # Match against the full virtual path or just the filename
            if fnmatch.fnmatch(virt, pattern) or fnmatch.fnmatch(
                virt.lstrip("/"), pattern.lstrip("/")
            ):
                results.append(self._blob_info(blob))
        results.sort(key=lambda x: x["path"])
        return results

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search file contents for a literal string pattern."""
        prefix = self._to_key(path or "/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        try:
            regex = re.compile(re.escape(pattern))
        except re.error as exc:
            return f"Invalid pattern: {exc}"

        blobs = self._client.list_blobs(self._bucket_name, prefix=prefix or None)
        matches: list[GrepMatch] = []
        for blob in blobs:
            virt = self._to_virtual(blob.name)
            if glob and not fnmatch.fnmatch(virt.split("/")[-1], glob):
                continue
            try:
                content = blob.download_as_text(encoding="utf-8")
            except Exception:
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    matches.append({"path": virt, "line": line_num, "text": line})
        return matches

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload raw bytes to GCS."""
        responses: list[FileUploadResponse] = []
        for virt_path, content in files:
            key = self._to_key(virt_path)
            blob = self._bucket.blob(key)
            try:
                blob.upload_from_string(content)
                responses.append(FileUploadResponse(path=virt_path, error=None))
            except PermissionError:
                responses.append(FileUploadResponse(path=virt_path, error="permission_denied"))
            except Exception:
                responses.append(FileUploadResponse(path=virt_path, error="invalid_path"))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files from GCS as raw bytes."""
        responses: list[FileDownloadResponse] = []
        for virt_path in paths:
            key = self._to_key(virt_path)
            blob = self._bucket.blob(key)
            try:
                content = blob.download_as_bytes()
                responses.append(FileDownloadResponse(path=virt_path, content=content, error=None))
            except NotFound:
                responses.append(FileDownloadResponse(path=virt_path, content=None, error="file_not_found"))
            except PermissionError:
                responses.append(FileDownloadResponse(path=virt_path, content=None, error="permission_denied"))
            except Exception:
                responses.append(FileDownloadResponse(path=virt_path, content=None, error="invalid_path"))
        return responses
