"""Desktop document view models and command payload helpers."""
from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

from talon_core.constants import DOCUMENT_WARN_EXTENSIONS, MAX_DOCUMENT_SIZE_BYTES
from talon_core.documents import (
    DocumentBlockedExtension,
    DocumentError,
    DocumentFilenameInvalid,
    DocumentIntegrityError,
    DocumentSizeExceeded,
)


@dataclasses.dataclass(frozen=True)
class DesktopDocumentItem:
    id: int
    filename: str
    mime_type: str
    size_bytes: int
    size_label: str
    description: str
    uploader_callsign: str
    uploaded_at: int
    uploaded_label: str
    sha256_hash: str
    hash_preview: str
    is_macro_risk: bool
    folder_path: str


def item_from_document_entry(entry: object) -> DesktopDocumentItem:
    document = getattr(entry, "document", entry)
    uploader = str(getattr(entry, "uploader_callsign", "UNKNOWN"))
    filename = str(getattr(document, "filename", ""))
    sha256_hash = str(getattr(document, "sha256_hash", ""))
    uploaded_at = int(getattr(document, "uploaded_at", 0) or 0)
    return DesktopDocumentItem(
        id=int(getattr(document, "id")),
        filename=filename,
        mime_type=str(getattr(document, "mime_type", "")),
        size_bytes=int(getattr(document, "size_bytes", 0) or 0),
        size_label=format_size(int(getattr(document, "size_bytes", 0) or 0)),
        description=str(getattr(document, "description", "") or ""),
        uploader_callsign=uploader,
        uploaded_at=uploaded_at,
        uploaded_label=format_uploaded_at(uploaded_at),
        sha256_hash=sha256_hash,
        hash_preview=hash_preview(sha256_hash),
        is_macro_risk=is_macro_risk_filename(filename),
        folder_path=str(getattr(document, "folder_path", "") or ""),
    )


def items_from_document_entries(entries: typing.Iterable[object]) -> list[DesktopDocumentItem]:
    return [item_from_document_entry(entry) for entry in entries]


def build_upload_payload(
    file_path: str | pathlib.Path,
    *,
    description: str = "",
    folder_path: str = "",
) -> dict[str, object]:
    path = pathlib.Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Document file not found: {path}")
    size = path.stat().st_size
    if size > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentSizeExceeded(
            f"File size {size:,} bytes exceeds the {MAX_DOCUMENT_SIZE_BYTES // 1024 // 1024} MB limit."
        )
    return {
        "raw_filename": path.name,
        "file_data": path.read_bytes(),
        "description": description.strip(),
        "folder_path": folder_path.strip().strip("/"),
    }


def format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def format_uploaded_at(uploaded_at: int) -> str:
    if uploaded_at <= 0:
        return "Unknown"
    return datetime.datetime.fromtimestamp(uploaded_at).strftime("%Y-%m-%d %H:%M")


def hash_preview(sha256_hash: str) -> str:
    if len(sha256_hash) <= 24:
        return sha256_hash
    return f"{sha256_hash[:24]}..."


def is_macro_risk_filename(filename: str) -> bool:
    return pathlib.Path(filename).suffix.lower() in DOCUMENT_WARN_EXTENSIONS


def can_upload_document(mode: str) -> bool:
    return mode == "server"


def can_delete_document(mode: str, item: DesktopDocumentItem | None) -> bool:
    return mode == "server" and item is not None


def can_download_document(item: DesktopDocumentItem | None) -> bool:
    return item is not None


def document_error_message(exc: BaseException) -> str:
    if isinstance(exc, DocumentSizeExceeded):
        return f"File too large: {exc}"
    if isinstance(exc, DocumentFilenameInvalid):
        return f"Invalid filename: {exc}"
    if isinstance(exc, DocumentBlockedExtension):
        return f"File type not allowed: {exc}"
    if isinstance(exc, DocumentIntegrityError):
        return f"Integrity check failed: {exc}"
    if isinstance(exc, DocumentError):
        return f"Document error: {exc}"
    return str(exc)
