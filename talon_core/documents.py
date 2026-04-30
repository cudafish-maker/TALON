"""
Document management — upload, download, delete, list.

Security model
--------------
Upload pipeline (fail-fast, cheapest checks first):
  1. Size cap (50 MB)
  2. Filename sanitization — strip path components, reject dotfiles
  3. Extension block-list  — no executables or scripts
  4. MIME magic bytes      — cross-checked against blocked MIME set
                             (python-magic required; falls back to mimetypes)
  5. Image re-encoding     — PIL strips EXIF and prevents polyglot attacks
                             (Pillow required; silently skipped if unavailable)
  6. SHA-256 hash          — stored in DB for download-time integrity check
  7. Field encryption      — PyNaCl SecretBox before any disk write
  8. Atomic file write     — tmp → os.replace(); partial writes never visible
  9. Path traversal check  — internal name must resolve within storage root

Download:
  Decrypt → SHA-256 verify → return plaintext.
  Caller is responsible for showing macro-risk warning (see DOCUMENT_WARN_EXTENSIONS).

Storage directory:
  Configured via talon.ini [documents] storage_path.
  Created at 0o700 on first write.
  Internal filenames: "{doc_id}_{uuid4}.bin"  (opaque, no original extension on disk).

Optional dependencies (graceful fallback if absent):
  python-magic  — requires libmagic1 on Linux (`apt install libmagic1`).
                  ImportError → extension-only MIME detection.
  Pillow        — ImportError → image re-encoding skipped (logged as warning).
"""
import hashlib
import io
import mimetypes
import os
import pathlib
import re
import time
import uuid

from talon_core.constants import (
    DOCUMENT_ALLOWED_EXTENSIONS,
    DOCUMENT_ALLOWED_MIMES,
    DOCUMENT_BLOCKED_EXTENSIONS,
    DOCUMENT_BLOCKED_MIMES,
    MAX_DOCUMENT_SIZE_BYTES,
)
from talon_core.crypto.fields import decrypt_field, encrypt_field
from talon_core.db.connection import Connection
from talon_core.db.models import Document
from talon_core.utils.logging import get_logger

_log = get_logger("documents")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DocumentError(Exception):
    """Base class for document-layer errors."""


class DocumentBlockedExtension(DocumentError):
    """File extension or MIME type is not permitted."""


class DocumentSizeExceeded(DocumentError):
    """File exceeds the maximum allowed size."""


class DocumentIntegrityError(DocumentError):
    """SHA-256 hash mismatch on download — file may be corrupted or tampered."""


class DocumentFilenameInvalid(DocumentError):
    """Filename could not be sanitized to a safe value."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SAFE_CHARS = re.compile(r"[^\w.\- ]")   # keep word chars, dot, dash, space

def _sanitize_filename(raw: str) -> str:
    """Return a safe display filename derived from *raw*.

    Steps:
      1. Strip surrounding whitespace.
      2. Take only the final path component (defends against both POSIX and
         Windows path separators).
      3. Replace unsafe characters with underscores.
      4. Collapse runs of underscores/spaces.
      5. Enforce max 255 chars.
      6. Reject dotfiles and empty results.

    Raises DocumentFilenameInvalid on any failure.
    """
    if not raw or not raw.strip():
        raise DocumentFilenameInvalid("Empty filename.")
    # Strip path separators from both POSIX and Windows paths
    name = pathlib.PurePosixPath(raw.strip()).name
    name = pathlib.PureWindowsPath(name).name
    if not name:
        raise DocumentFilenameInvalid(f"No filename component in {raw!r}.")
    name = _SAFE_CHARS.sub("_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    name = name[:255]
    if not name:
        raise DocumentFilenameInvalid(f"Filename {raw!r} reduced to empty after sanitization.")
    if name.startswith("."):
        raise DocumentFilenameInvalid(f"Dotfiles are not permitted: {name!r}.")
    return name


def sanitize_folder_path(raw: str | None) -> str:
    """Return a canonical slash-delimited document folder path."""
    if raw is None:
        return ""
    cleaned = str(raw).replace("\\", "/").strip().strip("/")
    if not cleaned:
        return ""
    parts: list[str] = []
    for part in cleaned.split("/"):
        segment = _SAFE_CHARS.sub("_", part.strip())
        segment = re.sub(r"_+", "_", segment).strip(" _")
        if not segment or segment in {".", ".."}:
            raise DocumentFilenameInvalid(f"Invalid folder component: {part!r}.")
        if segment.startswith("."):
            raise DocumentFilenameInvalid(f"Dot folders are not permitted: {segment!r}.")
        parts.append(segment[:96])
    folder_path = "/".join(parts)
    if len(folder_path) > 255:
        raise DocumentFilenameInvalid("Document folder path is too long.")
    return folder_path


def _detect_mime(data: bytes, filename: str) -> str:
    """Return the MIME type for *data*.

    Tries python-magic first (magic bytes); falls back to mimetypes extension
    lookup; falls back to 'application/octet-stream'.
    """
    try:
        import magic  # type: ignore
        return magic.from_buffer(data[:4096], mime=True) or "application/octet-stream"
    except ImportError:
        _log.debug("python-magic not available; using extension-based MIME detection.")
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _is_image_mime(mime: str) -> bool:
    return mime.startswith("image/")


def _sanitize_image(data: bytes, mime: str) -> bytes:
    """Re-encode an image through Pillow to strip EXIF and prevent polyglot files.

    Returns the re-encoded bytes, or the original bytes if Pillow is unavailable.
    If Pillow is installed but cannot re-encode the image, fail closed.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        _log.warning("Pillow not available; image re-encoding skipped (EXIF not stripped).")
        return data
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format or "PNG"
        buf = io.BytesIO()
        # Use a safe subset of formats; convert unusual formats to PNG
        if fmt.upper() not in {"JPEG", "PNG", "GIF", "BMP", "WEBP"}:
            fmt = "PNG"
        img.save(buf, format=fmt)
        return buf.getvalue()
    except Exception as exc:
        _log.warning("Image re-encoding failed for MIME %s: %s", mime, exc)
        raise DocumentBlockedExtension("Image could not be sanitized safely.") from exc


def _ensure_storage_dir(path: pathlib.Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def _check_path_in_root(storage_root: pathlib.Path, internal_name: str) -> pathlib.Path:
    """Return the resolved file path; raise DocumentError if it escapes the root."""
    resolved = (storage_root / internal_name).resolve()
    if resolved.parent != storage_root.resolve():
        raise DocumentError(
            f"Path traversal detected: {internal_name!r} resolves outside storage root."
        )
    return resolved


def _row_to_document(row: tuple) -> Document:
    (
        doc_id,
        filename,
        mime_type,
        size_bytes,
        file_path,
        sha256_hash,
        folder_path,
        description,
        uploaded_by,
        uploaded_at,
        version,
    ) = row
    return Document(
        id=doc_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        file_path=file_path,
        sha256_hash=sha256_hash,
        folder_path=folder_path,
        description=description,
        uploaded_by=uploaded_by,
        uploaded_at=uploaded_at,
        version=version,
    )


_SELECT = (
    "SELECT id, filename, mime_type, size_bytes, file_path, sha256_hash, "
    "folder_path, description, uploaded_by, uploaded_at, version FROM documents"
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upload_document(
    conn: Connection,
    key: bytes,
    storage_root: pathlib.Path,
    *,
    raw_filename: str,
    file_data: bytes,
    uploaded_by: int,
    description: str = "",
    folder_path: str = "",
) -> Document:
    """Validate, encrypt, and store a document.

    Raises:
        DocumentSizeExceeded       — file too large
        DocumentFilenameInvalid    — filename cannot be sanitized
        DocumentBlockedExtension   — extension or MIME type is blocked
        DocumentError              — path traversal or other storage error
    """
    # 1. Size cap
    if len(file_data) > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentSizeExceeded(
            f"File size {len(file_data):,} bytes exceeds the {MAX_DOCUMENT_SIZE_BYTES // 1024 // 1024} MB limit."
        )

    # 2. Filename sanitization
    filename = _sanitize_filename(raw_filename)
    folder_path = sanitize_folder_path(folder_path)
    suffix = pathlib.Path(filename).suffix.lower()

    # 3. Extension block-list
    if suffix in DOCUMENT_BLOCKED_EXTENSIONS:
        raise DocumentBlockedExtension(f"File type {suffix!r} is not permitted.")

    # 4. MIME magic bytes
    mime_type = _detect_mime(file_data, filename)
    if not _is_allowed_upload_type(suffix, mime_type):
        raise DocumentBlockedExtension(
            f"File type {suffix or '<none>'!r} with content {mime_type!r} is not permitted."
        )
    if mime_type in DOCUMENT_BLOCKED_MIMES:
        raise DocumentBlockedExtension(
            f"File content detected as {mime_type!r}, which is not permitted."
        )

    # 5. Image re-encoding (strips EXIF, prevents polyglot files)
    if _is_image_mime(mime_type):
        file_data = _sanitize_image(file_data, mime_type)

    # 6. SHA-256 hash of final plaintext
    sha256_hash = hashlib.sha256(file_data).hexdigest()

    # 7. Encrypt
    encrypted = encrypt_field(file_data, key)

    # 8. Insert DB row with placeholder file_path; get real id
    now = int(time.time())
    cursor = conn.execute(
        "INSERT INTO documents "
        "(filename, mime_type, size_bytes, file_path, sha256_hash, folder_path, "
        "description, uploaded_by, uploaded_at, version) "
        "VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, 1)",
        (
            filename,
            mime_type,
            len(file_data),
            sha256_hash,
            folder_path,
            description,
            uploaded_by,
            now,
        ),
    )
    doc_id = cursor.lastrowid
    internal_name = f"{doc_id}_{uuid.uuid4().hex}.bin"

    # 9. Path traversal check
    _ensure_storage_dir(storage_root)
    file_path = _check_path_in_root(storage_root, internal_name)

    # 10. Atomic write: tmp → replace
    tmp_path = storage_root / (internal_name + ".tmp")
    try:
        tmp_path.write_bytes(encrypted)
        os.replace(tmp_path, file_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        conn.rollback()
        raise

    # 11. Update file_path in DB and commit
    conn.execute(
        "UPDATE documents SET file_path = ? WHERE id = ?",
        (internal_name, doc_id),
    )
    conn.commit()

    # 12. Audit
    try:
        from talon_core.utils.logging import audit
        audit(
            "document_uploaded",
            doc_id=doc_id,
            filename=filename,
            size_bytes=len(file_data),
            mime_type=mime_type,
            uploaded_by=uploaded_by,
        )
    except Exception:
        pass  # audit failure must not roll back a successful upload

    _log.info("Document uploaded: id=%s filename=%r size=%s", doc_id, filename, len(file_data))
    return get_document(conn, doc_id)


def download_document(
    conn: Connection,
    key: bytes,
    storage_root: pathlib.Path,
    doc_id: int,
    *,
    downloader_id: int,
) -> tuple[Document, bytes]:
    """Decrypt and integrity-check a document.

    Returns (Document, plaintext_bytes).

    Raises:
        DocumentError          — document not found
        DocumentIntegrityError — SHA-256 mismatch (corruption or tampering)
    """
    doc = get_document(conn, doc_id)
    if not doc.file_path:
        raise DocumentError(f"Document {doc.filename!r} is not cached locally.")
    file_path = _check_path_in_root(storage_root, doc.file_path)

    encrypted = file_path.read_bytes()
    plaintext = decrypt_field(encrypted, key)

    # Integrity check
    actual_hash = hashlib.sha256(plaintext).hexdigest()
    if actual_hash != doc.sha256_hash:
        _log.error(
            "Integrity check FAILED for doc id=%s: stored=%s actual=%s",
            doc_id, doc.sha256_hash, actual_hash,
        )
        raise DocumentIntegrityError(
            f"Document {doc.filename!r} failed integrity check. "
            "The file may be corrupted or tampered with."
        )

    try:
        from talon_core.utils.logging import audit
        audit(
            "document_downloaded",
            doc_id=doc_id,
            filename=doc.filename,
            downloader_id=downloader_id,
        )
    except Exception:
        pass

    _log.info("Document downloaded: id=%s filename=%r", doc_id, doc.filename)
    return doc, plaintext


def cache_document_download(
    conn: Connection,
    key: bytes,
    storage_root: pathlib.Path,
    doc_id: int,
    plaintext: bytes,
) -> Document:
    """Store a downloaded plaintext document in the local encrypted cache."""
    doc = get_document(conn, doc_id)
    actual_hash = hashlib.sha256(plaintext).hexdigest()
    if actual_hash != doc.sha256_hash:
        raise DocumentIntegrityError(
            f"Document {doc.filename!r} failed integrity check. "
            "The file may be corrupted or tampered with."
        )

    internal_name = f"{doc_id}_{actual_hash[:16]}.bin"
    encrypted = encrypt_field(plaintext, key)

    _ensure_storage_dir(storage_root)
    cache_path = _check_path_in_root(storage_root, internal_name)
    tmp_path = storage_root / (internal_name + ".tmp")
    try:
        tmp_path.write_bytes(encrypted)
        os.replace(tmp_path, cache_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    old_internal_name = doc.file_path
    if old_internal_name and old_internal_name != internal_name:
        try:
            old_path = _check_path_in_root(storage_root, old_internal_name)
            old_path.unlink(missing_ok=True)
        except Exception as exc:
            _log.warning(
                "Could not remove stale cached document id=%s path=%r: %s",
                doc_id,
                old_internal_name,
                exc,
            )

    if doc.file_path != internal_name:
        conn.execute(
            "UPDATE documents SET file_path = ? WHERE id = ?",
            (internal_name, doc_id),
        )
        conn.commit()
        doc = get_document(conn, doc_id)

    _log.info("Document cached locally: id=%s filename=%r", doc_id, doc.filename)
    return doc


def move_document(conn: Connection, doc_id: int, *, folder_path: str) -> Document:
    """Move an existing document into a logical explorer folder."""
    doc = get_document(conn, doc_id)
    next_folder = sanitize_folder_path(folder_path)
    if doc.folder_path == next_folder:
        return doc
    conn.execute(
        "UPDATE documents SET folder_path = ?, version = version + 1 WHERE id = ?",
        (next_folder, int(doc_id)),
    )
    conn.commit()
    return get_document(conn, doc_id)


def _is_allowed_upload_type(suffix: str, mime_type: str) -> bool:
    suffix = suffix.lower()
    mime_type = mime_type.lower()
    if suffix not in DOCUMENT_ALLOWED_EXTENSIONS:
        return False
    if mime_type in DOCUMENT_ALLOWED_MIMES:
        return True
    if suffix in {".txt", ".md", ".markdown", ".csv", ".json", ".geojson"}:
        return mime_type.startswith("text/")
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
        return mime_type.startswith("image/")
    return False


def evict_document_cache(
    conn: Connection,
    storage_root: pathlib.Path,
    doc_id: int,
    *,
    clear_db_path: bool = True,
    commit: bool = True,
) -> bool:
    """Remove any locally cached document blob for *doc_id*.

    Returns True when a cached file path was present, regardless of whether the
    filesystem entry already existed.
    """
    row = conn.execute(
        "SELECT file_path FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if row is None:
        return False

    internal_name = row[0] or ""
    if not internal_name:
        return False

    try:
        cache_path = _check_path_in_root(storage_root, internal_name)
        cache_path.unlink(missing_ok=True)
    except Exception as exc:
        _log.warning(
            "Could not remove cached document id=%s path=%r: %s",
            doc_id,
            internal_name,
            exc,
        )

    if clear_db_path:
        conn.execute(
            "UPDATE documents SET file_path = '' WHERE id = ?",
            (doc_id,),
        )
        if commit:
            conn.commit()

    return True


def delete_document(
    conn: Connection,
    storage_root: pathlib.Path,
    doc_id: int,
) -> None:
    """Delete a document from both disk and the database.

    Server-operator only — the caller must enforce this access control.
    """
    doc = get_document(conn, doc_id)

    # Delete from filesystem first (missing_ok handles an already-deleted file)
    if doc.file_path:
        try:
            file_path = _check_path_in_root(storage_root, doc.file_path)
            file_path.unlink(missing_ok=True)
        except Exception as exc:
            _log.warning("Could not delete file for doc id=%s: %s", doc_id, exc)

    with conn.transaction():
        conn.execute("DELETE FROM sitrep_documents WHERE document_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    try:
        from talon_core.utils.logging import audit
        audit("document_deleted", doc_id=doc_id, filename=doc.filename)
    except Exception:
        pass

    _log.info("Document deleted: id=%s filename=%r", doc_id, doc.filename)


def list_documents(conn: Connection, *, limit: int = 200) -> list[Document]:
    """Return documents ordered newest first (no file content in memory)."""
    rows = conn.execute(
        f"{_SELECT} ORDER BY folder_path ASC, uploaded_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_row_to_document(r) for r in rows]


def get_document(conn: Connection, doc_id: int) -> Document:
    """Load a single document row by id.

    Raises DocumentError if not found.
    """
    row = conn.execute(f"{_SELECT} WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        raise DocumentError(f"Document id={doc_id} not found.")
    return _row_to_document(row)


def cleanup_incomplete_uploads(conn: Connection, storage_root: pathlib.Path) -> int:
    """Remove DB rows with empty file_path (crashed mid-upload).

    Called at server startup after the DB is opened.
    Returns the number of rows removed.
    """
    rows = conn.execute(
        "SELECT id, filename FROM documents WHERE file_path = ''"
    ).fetchall()
    if not rows:
        return 0
    ids = [r[0] for r in rows]
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", ids)
    conn.commit()
    _log.warning(
        "Cleaned up %d incomplete document upload(s): ids=%s",
        len(ids), ids,
    )
    return len(ids)
