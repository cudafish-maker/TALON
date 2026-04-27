# Document Management — Plan & Status

_Last updated: 2026-04-25. Update this file at the end of every session that touches document management._

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| DB migration 0006 | `[x]` | Adds `file_path`, `sha256_hash`, `description`; drops `data`. Historical document migration is applied; current project schema is v15. |
| `Document` dataclass update | `[x]` | Remove `data: bytes`, add new fields |
| New constants | `[x]` | `MAX_DOCUMENT_SIZE_BYTES`, blocked/warn/blocked-MIME sets |
| `config.py` — storage path | `[x]` | `get_document_storage_path()` |
| Client/server document fetch over RNS | `[x]` | Clients request document plaintext over the persistent sync link; successful responses use `RNS.Resource` and update the local encrypted cache |
| `talon/documents.py` | `[x]` | Full backend: 12-step upload pipeline, download + integrity check, delete, list, cleanup, and client-local cache helpers (`cache_document_download()`, `evict_document_cache()`) |
| `document.kv` | `[x]` | Root layout only |
| `document_screen.py` | `[x]` | `DocumentScreen` + `_DocumentRow` + all dialogs; client downloads now fetch in a worker thread and reuse the same macro warning/save path after local cache fill |
| `app.py` registration | `[x]` | Added to `_register_shared_screens` |
| Desktop navigation | `[ ]` | `DocumentScreen` is registered, but the current programmatic desktop dashboard does not expose a visible Documents control; tracked as BUG-085 |
| `talon.ini.example` | `[x]` | `[documents] storage_path =` section added |
| `pyproject.toml` | `[x]` | `python-magic` and `Pillow` are core runtime dependencies because the document pipeline is part of the app surface; PyInstaller remains desktop-only optional dependency |

---

## Context

TALON needs a shared document repository — a "tactical drive" where any operator can upload and download files. The server stores all documents; clients sync via Reticulum (Phase 2). The threat model includes compromised operators uploading malicious files that other operators download and execute. Two security surfaces must be protected: the server (against malicious uploads) and clients (against malicious downloads).

Current state: full server-side CRUD + secure upload pipeline is implemented. Phase 2 client document opening is implemented over the persistent broadband sync link via on-demand fetch plus local encrypted cache. Client upload remains pending, the first client open of a document still requires an active sync link, and the desktop dashboard currently needs a visible navigation control for the registered Documents screen (BUG-085).

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
| `talon/ui/screens/main_screen.py` | Add a visible desktop control that navigates to `documents` (BUG-085) |
| `talon.ini.example` / `talon.ini` | Add `[documents] storage_path =` section |
| `pyproject.toml` | Keep `python-magic>=0.4.27` and `Pillow>=10.0.0` in core runtime dependencies; keep `pyinstaller` in the desktop optional dependency only |

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

This was the historical schema-6 change. The current `DB_SCHEMA_VERSION` is 15, and `talon/db/migrations.py` asserts that `len(MIGRATIONS) == DB_SCHEMA_VERSION`.

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
    def _do_download(modal, doc)    # server: local download_document(); client: fetch_document() → local cache → macro warning → save
    def _confirm_delete(doc)        # confirmation modal (server mode only)
    def _do_delete(modal, doc)      # delete_document()

class _DocumentRow(MDBoxLayout):
    # height=64dp, horizontal: [mime-icon | name+size+uploader | OPEN btn]
    # mime icon chosen by mime_type prefix: pdf / image / generic
```

**Mode guards:**
- Upload and delete: check `app.mode == "server"`. Client mode still shows an informational upload message.
- Download: works in both modes. Server mode reads the local encrypted blob directly; client mode reuses a local encrypted cache when present and otherwise requests plaintext from the server over the persistent sync link before caching locally.

**Client mode Phase 2:** Synced document metadata appears in the normal list. Opening a document triggers an on-demand fetch over the persistent broadband link when the local cache is empty or stale; successful fetches are stored as locally encrypted blobs and invalidated when the document hash/version changes or the row is deleted.

---

## 8. `app.py` Registration

```python
# In _register_shared_screens():
from talon.ui.screens.document_screen import DocumentScreen
sm.add_widget(DocumentScreen(name="documents"))
```

---

## 9. Desktop Navigation

`DocumentScreen` is registered in `talon/app.py`, but the current desktop
dashboard is built programmatically in `MainScreen._build_desktop_layout()` and
only exposes quick-nav controls for mission, SITREP, and chat. Add a visible
desktop Documents control or restore a shared navigation surface that includes
`documents`; see BUG-085.

---

## 10. `pyproject.toml`

```toml
[project]
dependencies = [
    "python-magic>=0.4.27",
    "Pillow>=10.0.0",
]

[project.optional-dependencies]
desktop = ["pyinstaller>=6.19"]
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
- [~] Client mode: synced metadata lists and open/download works when the Documents screen is reached; current desktop dashboard navigation to that screen is missing (BUG-085)
