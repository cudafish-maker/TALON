"""
Shared pytest fixtures.

tmp_db  — an open, migrated SQLCipher connection in a temp directory.
           Returns (conn, db_path). Closed automatically after each test.
test_key — deterministic 32-byte key for field-encryption tests.
"""
import pathlib

import pytest

from talon.db.connection import open_db, close_db
from talon.db.migrations import apply_migrations

# Stable test key — never use outside tests.
TEST_KEY = bytes(range(32))
TEST_PASSPHRASE = "test-passphrase"


@pytest.fixture
def test_key() -> bytes:
    return TEST_KEY


@pytest.fixture
def tmp_db(tmp_path: pathlib.Path):
    """Open a fresh, migrated SQLCipher database for each test."""
    db_path = tmp_path / "test.db"
    conn = open_db(db_path, TEST_KEY)
    apply_migrations(conn)
    yield conn, db_path
    close_db(conn)
