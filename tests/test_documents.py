"""Tests for document upload hardening."""

import hashlib
import sys
import types

import pytest

from talon.db.connection import close_db, open_db
from talon.db.migrations import apply_migrations
from talon.documents import (
    DocumentBlockedExtension,
    cache_document_download,
    download_document,
    evict_document_cache,
    upload_document,
    _sanitize_image,
)


def _open_test_db(tmp_path, name: str, key: bytes):
    conn = open_db(tmp_path / name, key)
    apply_migrations(conn)
    return conn


def test_sanitize_image_fails_closed_when_pillow_reencode_fails(monkeypatch):
    fake_pil = types.ModuleType("PIL")

    class FakeImage:
        @staticmethod
        def open(_data):
            raise OSError("bad image")

    fake_pil.Image = FakeImage
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", FakeImage)

    with pytest.raises(DocumentBlockedExtension):
        _sanitize_image(b"not really an image", "image/png")


def test_cache_document_download_stores_local_encrypted_blob(tmp_path, test_key):
    server_conn = _open_test_db(tmp_path, "server.db", test_key)
    client_key = bytes(reversed(test_key))
    client_conn = _open_test_db(tmp_path, "client.db", client_key)

    try:
        uploaded = upload_document(
            server_conn,
            test_key,
            tmp_path / "server-docs",
            raw_filename="brief.txt",
            file_data=b"field notes",
            uploaded_by=1,
        )
        plaintext = b"field notes"

        client_conn.execute(
            "INSERT INTO documents "
            "(id, filename, mime_type, size_bytes, sha256_hash, description, "
            "uploaded_by, uploaded_at, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uploaded.id,
                uploaded.filename,
                uploaded.mime_type,
                uploaded.size_bytes,
                uploaded.sha256_hash,
                uploaded.description,
                uploaded.uploaded_by,
                uploaded.uploaded_at,
                uploaded.version,
            ),
        )
        client_conn.commit()

        client_storage = tmp_path / "client-docs"
        cached = cache_document_download(
            client_conn,
            client_key,
            client_storage,
            uploaded.id,
            plaintext,
        )

        cached_path = client_storage / cached.file_path
        assert cached_path.exists()
        assert cached_path.read_bytes() != plaintext

        loaded, cached_plaintext = download_document(
            client_conn,
            client_key,
            client_storage,
            uploaded.id,
            downloader_id=1,
        )
        assert loaded.file_path == cached.file_path
        assert cached_plaintext == plaintext
    finally:
        close_db(server_conn)
        close_db(client_conn)


def test_evict_document_cache_removes_file_and_clears_file_path(tmp_path, test_key):
    conn = _open_test_db(tmp_path, "client.db", test_key)

    try:
        plaintext = b"cached file"
        sha256_hash = hashlib.sha256(plaintext).hexdigest()
        conn.execute(
            "INSERT INTO documents "
            "(id, filename, mime_type, size_bytes, sha256_hash, description, "
            "uploaded_by, uploaded_at, version) "
            "VALUES (?, ?, ?, ?, ?, '', 1, 1000, 1)",
            (7, "cache.txt", "text/plain", len(plaintext), sha256_hash),
        )
        conn.commit()

        storage_root = tmp_path / "client-docs"
        cached = cache_document_download(conn, test_key, storage_root, 7, plaintext)
        cached_path = storage_root / cached.file_path
        assert cached_path.exists()

        assert evict_document_cache(conn, storage_root, 7) is True
        row = conn.execute(
            "SELECT file_path FROM documents WHERE id = 7"
        ).fetchone()
        assert row == ("",)
        assert not cached_path.exists()
    finally:
        close_db(conn)
