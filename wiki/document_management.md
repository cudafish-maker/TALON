# Document Management — Plan & Status

_Last updated: 2026-04-16. Update this file at the end of every session that touches document management._

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| DB migration 0006 | `[x]` | Add `file_path`, `sha256_hash`, `description`; drop `data`; bump schema to 6 |
| `Document` dataclass update | `[x]` | Remove `data: bytes`, add new fields |
| New constants | `[x]` | `MAX_DOCUMENT_SIZE_BYTES`, blocked/warn/blocked-MIME sets |
| `config.py` — storage path | `[x]` | `get_document_storage_path()` |
| `talon/documents.py` | `[x]` | Full backend: 12-step upload pipeline, download + integrity check, delete, list, cleanup |
| `document.kv` | `[x]` | Root layout only |
| `document_screen.py` | `[x]` | `DocumentScreen` + `_DocumentRow` + all dialogs (file chooser, upload, detail, macro warning, save, delete confirm) |
| `app.py` registration | `[x]` | Added to `_register_shared_screens` |
| `main_screen.py` nav | `[x]` | Added to shared nav items |
| `talon.ini.example` | `[x]` | `[documents] storage_path =` section added |
| `pyproject.toml` | `[x]` | `documents` optional dep group + added to `dev` group |

---

## Context

TALON needs a shared document repository — a "tactical drive" where any operator can upload and download files. The server stores all documents; clients sync via Reticulum (Phase 2). The threat model includes compromised operators uploading malicious files that other operators download and execute. Two security surfaces must be protected: the server (against malicious uploads) and clients (against malicious downloads).

Phase 1 delivers: full server-side CRUD + secure upload pipeline. Client-side network sync is Phase 2.

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `talon/constants.py` | Add `MAX_DOCUMENT_SIZE_BYTES`, `DOCUMENT_BLOCKED_EXTENSIONS`, `DOCUMENT_WARN_EXTENSIONS`; bump `DB_SCHEMA_VERSION` → 6 |
| `talon/config.py` | Add `get_document_storage_path(cfg)` |
| `talon/db/migrations.py` | Add migration 0006 (add columns, drop `data`, add indexes) |
| `talon/db/models.py` | Replace `Document` dataclass (remove `data: bytes`, add `file_path`, `sha256_hash`, `description`) |
| `talon/documents.py` | **NEW** — full upload/download/delete/list backend with security pipeline |
| `talon/ui/screens/document_screen.py` | **NEW** — `DocumentScreen` + `_DocumentRow`; all dialogs in Python |
| `talon/ui/kv/document.kv` | **NEW** — root screen layout only (header, divider, scrollable list) |
| `talon/app.py` | Register `DocumentScreen` in `_register_shared_screens` |
| `talon/ui/screens/main_screen.py` | Add `("Documents", "documents")` to `shared_items` |
| `talon.ini.example` / `talon.ini` | Add `[documents] storage_path =` section |
| `pyproject.toml` | Add `documents` optional-dep group (`python-magic>=0.4.27`, `Pillow>=10.0.0`); add to `dev` group |

---

## 1. DB Migration 0006

Append to `MIGRATIONS` list in `talon/db/migrations.py`:

```sql
ALTER TABLE documents ADD COLUMN file_path   TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN sha256_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE documents DROP COLUMN data;

CREATE INDEX idx_documents_uploaded_at ON documents(uploaded_at);
CREATE INDEX idx_documents_uploaded_by ON documents(uploaded_by);
```

Bump `DB_SCHEMA_VERSION = 6` in `talon/constants.py` (the assert at migrations.py:197 enforces `len(MIGRATIONS) == DB_SCHEMA_VERSION`).

---

## 2. Updated `Document` Dataclass (`talon/db/models.py`)

Replace existing `Document`:
```python
@dataclasses.dataclass
class Document:
    id: int
    filename: str       # sanitized original name — display only
    mime_type: str      # verified MIME type
    size_bytes: int     # plaintext size
    file_path: str      # opaque internal name: "{id}_{uuid4}.bin"
    sha256_hash: str    # hex SHA-256 of plaintext (integrity check)
    description: str    # operator-supplied note
    uploaded_by: int    # FK → operators.id
    uploaded_at: int    # Unix timestamp
    version: int
```

---

## 3. New Constants (`talon/constants.py`)

```python
MAX_DOCUMENT_SIZE_BYTES: Final = 50 * 1024 * 1024   # 50 MB hard cap

# Show a macro-risk warning on download for these extensions
DOCUMENT_WARN_EXTENSIONS: Final = frozenset({
    ".doc", ".docx", ".docm", ".xls", ".xlsx", ".xlsm", ".xlsb",
    ".ppt", ".pptx", ".pptm", ".odt", ".ods", ".odp", ".rtf",
})

# Reject on upload — executable or script-interpretable
DOCUMENT_BLOCKED_EXTENSIONS: Final = frozenset({
    ".exe", ".com", ".msi", ".bat", ".cmd",
    ".sh", ".bash", ".zsh", ".fish",
    ".py", ".pyw", ".pyc", ".rb", ".pl", ".php",
    ".js", ".mjs", ".cjs", ".ts",
    ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".wsf",
    ".jar", ".class", ".elf", ".so", ".dll",
    ".apk", ".ipa", ".scr", ".pif", ".lnk",
})

# MIME types to block regardless of extension (magic-bytes detection)
DOCUMENT_BLOCKED_MIMES: Final = frozenset({
    "application/x-executable", "application/x-elf",
    "application/x-msdos-program", "application/x-msdownload",
    "text/x-shellscript", "application/x-sh", "application/java-archive",
})
```

---

## 4. Config (`talon/config.py`)

Add after `get_rns_config_dir`:
```python
def get_document_storage_path(cfg: configparser.ConfigParser) -> pathlib.Path:
    raw = cfg.get("documents", "storage_path", fallback="").strip()
    return pathlib.Path(raw) if raw else _get_data_dir(cfg) / "documents"
```

---

## 5. `talon/documents.py` — Security Pipeline

### Exceptions
```python
class DocumentError(Exception): ...
class DocumentBlockedExtension(DocumentError): ...
class DocumentSizeExceeded(DocumentError): ...
class DocumentIntegrityError(DocumentError): ...
class DocumentFilenameInvalid(DocumentError): ...
```

### Upload security check order (fail-fast, cheapest first)

| # | Check | Raises |
|---|-------|--------|
| 1 | `len(file_data) > MAX_DOCUMENT_SIZE_BYTES` | `DocumentSizeExceeded` |
| 2 | `_sanitize_filename(raw_filename)` — strip path components, sanitize chars, reject dotfiles, max 255 chars | `DocumentFilenameInvalid` |
| 3 | Extension block-list (lowercased suffix in `DOCUMENT_BLOCKED_EXTENSIONS`) | `DocumentBlockedExtension` |
| 4 | MIME magic bytes — `python-magic` if available, fallback to `mimetypes.guess_type`; cross-check against `DOCUMENT_BLOCKED_MIMES` | `DocumentBlockedExtension` |
| 5 | Image re-encode — if MIME is `image/*`, pass through `PIL.Image` open→save to strip EXIF and prevent polyglot files; silently skipped if Pillow unavailable | — |
| 6 | SHA-256 of (possibly re-encoded) plaintext | stored in DB |
| 7 | Encrypt: `encrypt_field(file_data, key)` from `talon/crypto/fields.py` | — |
| 8 | Insert DB row with `file_path=''`; get `lastrowid` → construct `"{id}_{uuid4}.bin"` | — |
| 9 | Path traversal check: `(storage_root / name).resolve().parent == storage_root.resolve()` | `DocumentError` |
| 10 | Atomic write: write to `{name}.tmp`, then `os.replace()` to final path | — |
| 11 | `UPDATE documents SET file_path=? WHERE id=?` + `conn.commit()` | — |
| 12 | Audit: `document_uploaded` (doc_id, filename, size_bytes, uploaded_by) | — |

### Function signatures

```python
def upload_document(conn, key, storage_root, *, raw_filename, file_data,
                    uploaded_by, description="") -> Document

def download_document(conn, key, storage_root, doc_id, *, downloader_id) -> tuple[Document, bytes]
    # load row → path traversal check → read encrypted file →
    # decrypt → SHA-256 verify → audit document_downloaded → return (doc, plaintext)

def delete_document(conn, storage_root, doc_id) -> None
    # load row → unlink file (missing_ok=True) → DELETE row → commit → audit document_deleted

def list_documents(conn, *, limit=200) -> list[Document]
    # SELECT without file content — index only

def get_document(conn, doc_id) -> Document

def cleanup_incomplete_uploads(conn, storage_root) -> int
    # Delete DB rows with file_path='' (crashed mid-upload); return count cleaned
    # Called at server startup after DB open
```

Storage dir created at `0o700` on first upload via `storage_root.mkdir(mode=0o700, parents=True, exist_ok=True)`.

### Optional dependencies (graceful fallback)
- `python-magic` — requires system `libmagic1` (`apt install libmagic1`). `ImportError` → extension-only MIME check.
- `Pillow` — `ImportError` → image re-encoding skipped (logged as warning).

---

## 6. `document.kv` Layout

```
<DocumentScreen>
  MDBoxLayout (vertical)
    MDBoxLayout (horizontal, 48dp)       ← header
      MDIconButton  icon=arrow-left → on_back_pressed()
      MDLabel  "DOCUMENTS"
      MDIconButton  icon=refresh → on_refresh_pressed()
      MDIconButton  icon=upload → on_upload_pressed()
    MDDivider
    MDBoxLayout (horizontal, 28dp)       ← column headers
      "Filename" | "Type / Size" | "Uploaded"
    MDDivider
    MDScrollView
      MDBoxLayout  id=document_list  adaptive_height=True
```

All dialogs (file chooser, upload detail, download warning, detail panel, delete confirm) are built in Python following the `ModalView(size_hint=(0.65, None), auto_dismiss=False)` pattern used by `asset_screen.py`.

---

## 7. `document_screen.py` Structure

```python
class DocumentScreen(MDScreen):
    def on_pre_enter()              # _load_documents()
    def on_back_pressed()           # manager.current = "main"
    def on_refresh_pressed()        # _load_documents()
    def on_upload_pressed()         # FileChooserListView modal → _open_upload_detail()
    def _load_documents()           # list_documents(conn) → build _DocumentRow widgets
    def _open_upload_detail(path)   # second modal: filename/desc/UPLOAD btn
    def _do_upload(modal, path, desc)   # upload_document(); handle exceptions → status label
    def _open_detail_dialog(doc)    # filename, size, uploader, hash preview, DOWNLOAD + DELETE
    def _do_download(modal, doc)    # download_document() → integrity → macro warning → save
    def _confirm_delete(doc)        # confirmation modal (server mode only)
    def _do_delete(modal, doc)      # delete_document()

class _DocumentRow(MDBoxLayout):
    # height=64dp, horizontal: [mime-icon | name+size+uploader | OPEN btn]
    # mime icon chosen by mime_type prefix: pdf / image / generic
```

**Mode guards:**
- Upload and delete: check `app.mode == "server"`. Client mode shows "Document sync not yet available."
- Download: works in both modes (Phase 1: server reads local disk; Phase 2: client receives via sync).

**Client mode Phase 1:** Screen registers and loads correctly; document list is empty (sync not yet wired); upload shows informational message.

---

## 8. `app.py` Registration

```python
# In _register_shared_screens():
from talon.ui.screens.document_screen import DocumentScreen
sm.add_widget(DocumentScreen(name="documents"))
```

---

## 9. `main_screen.py` Nav Menu

```python
shared_items = [
    ("Assets",     "assets"),
    ("SITREPs",    "sitrep"),
    ("Missions",   "mission"),
    ("Chat",       "chat"),
    ("Documents",  "documents"),   # ← add
]
```

---

## 10. `pyproject.toml`

```toml
[project.optional-dependencies]
documents = ["python-magic>=0.4.27", "Pillow>=10.0.0"]
# Also add both to the dev group
```

---

## Verification Checklist

- [ ] Migration: delete `talon.db`, relaunch — `PRAGMA table_info(documents)` shows `file_path`, `sha256_hash`, `description`; no `data` column
- [ ] Upload `.pdf` → appears in list; encrypted `.bin` in storage dir; audit log shows `document_uploaded`
- [ ] Upload `.sh` → rejected "File type not allowed"; nothing written to disk
- [ ] Rename `script.sh` → `script.pdf`; upload → MIME magic detects shell script → rejected
- [ ] Corrupt `.bin` on disk; download → `DocumentIntegrityError` shown; no data returned
- [ ] Upload `.docx`; download → macro warning dialog shown before save
- [ ] Delete (server) → `.bin` removed from disk; DB row gone; audit log shows `document_deleted`
- [ ] Filename `../../etc/passwd` → sanitized to `passwd`; path traversal check passes
- [ ] Client mode: Documents in nav; empty list; upload shows informational message
