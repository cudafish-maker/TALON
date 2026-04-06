# tests/test_server.py
# Tests for server-side logic (auth, audit, client registry, notifications).

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.server.app import TalonServer
from talon.server.audit import (
    format_audit_entry,
    log_event,
    log_sitrep_created,
)
from talon.server.auth import enroll_client, generate_enrollment_token
from talon.server.client_registry import ClientRegistry
from talon.server.notifications import (
    build_notification,
    chat_notification,
    sitrep_notification,
)

# ---------- First-run detection ----------


def test_is_first_run_true_when_no_salt(tmp_path):
    """is_first_run should return True when the salt file does not exist."""
    server = TalonServer()
    server.config = {"database": {"path": str(tmp_path / "server.db")}}
    assert server.is_first_run() is True


def test_is_first_run_false_when_salt_present(tmp_path):
    """is_first_run should return False once setup_database has written a salt."""
    db_path = tmp_path / "server.db"
    salt_path = str(db_path) + ".salt"
    with open(salt_path, "wb") as f:
        f.write(b"x" * 16)

    server = TalonServer()
    server.config = {"database": {"path": str(db_path)}}
    assert server.is_first_run() is False


# ---------- Auth / Enrollment ----------


def test_enrollment_token_format():
    """Enrollment token should be a 32-character hex string."""
    token = generate_enrollment_token()
    assert len(token) == 32
    assert all(c in "0123456789abcdef" for c in token)


def test_enrollment_token_unique():
    """Each token should be different."""
    tokens = [generate_enrollment_token() for _ in range(10)]
    assert len(set(tokens)) == 10


def test_enroll_valid_token():
    """Enrollment with a valid token should succeed."""
    token = generate_enrollment_token()
    valid_tokens = {token: {"used": False}}

    server_secret = b"test-server-secret-key"
    result = enroll_client(token, "identity-hash-123", "Alpha", valid_tokens, server_secret)
    assert result["success"] is True
    assert result["callsign"] == "Alpha"


def test_enroll_invalid_token():
    """Enrollment with an invalid token should fail."""
    valid_tokens = {}
    server_secret = b"test-server-secret-key"
    result = enroll_client("bad-token", "identity-hash", "Alpha", valid_tokens, server_secret)
    assert result["success"] is False


def test_enroll_used_token():
    """A used token should not be accepted again."""
    token = generate_enrollment_token()
    valid_tokens = {token: {"used": True}}

    server_secret = b"test-server-secret-key"
    result = enroll_client(token, "identity-hash", "Alpha", valid_tokens, server_secret)
    assert result["success"] is False


# ---------- Audit ----------


def test_log_event():
    """log_event should create an AuditEntry with correct fields."""
    entry = log_event("TEST_EVENT", "Alpha", target="asset-1", details="Test detail")
    assert entry.event_type == "TEST_EVENT"
    assert entry.client_callsign == "Alpha"
    assert "asset-1" in entry.details


def test_format_audit_entry():
    """Formatted entry should be a readable string."""
    entry = log_sitrep_created("Alpha", "sr-123", "FLASH")
    formatted = format_audit_entry(entry)
    assert "SITREP_CREATED" in formatted
    assert "Alpha" in formatted
    assert "sr-123" in formatted


# ---------- Client Registry ----------


def test_register_client():
    registry = ClientRegistry()
    record = registry.register("client-1", "Alpha", "yggdrasil")
    assert record["callsign"] == "Alpha"
    assert record["status"] == "ONLINE"


def test_mark_stale():
    registry = ClientRegistry()
    registry.register("client-1", "Alpha")
    registry.mark_stale("client-1")
    assert registry.get_client("client-1")["status"] == "STALE"


def test_revoke_adds_to_deny_list():
    registry = ClientRegistry()
    registry.register("client-1", "Alpha")
    registry.revoke("client-1", reason="Lost device")

    assert registry.is_denied("client-1") is True
    assert registry.get_client("client-1")["status"] == "REVOKED"


def test_get_by_callsign():
    registry = ClientRegistry()
    registry.register("client-1", "Alpha")
    registry.register("client-2", "Bravo")

    record = registry.get_by_callsign("Bravo")
    assert record is not None
    assert record["client_id"] == "client-2"


def test_get_online_clients():
    registry = ClientRegistry()
    registry.register("client-1", "Alpha")
    registry.register("client-2", "Bravo")
    registry.mark_stale("client-2")

    online = registry.get_online_clients()
    assert len(online) == 1
    assert online[0]["callsign"] == "Alpha"


# ---------- Notifications ----------


def test_build_notification():
    notif = build_notification("TEST", "Alpha", importance="PRIORITY", title="Test", body="A test notification")
    assert notif["type"] == "notification"
    assert notif["event"] == "TEST"
    assert notif["importance"] == "PRIORITY"


def test_sitrep_notification():
    notif = sitrep_notification("Alpha", "sr-1", "FLASH", is_append=False)
    assert notif["event"] == "SITREP_CREATED"
    assert notif["importance"] == "FLASH"


def test_chat_notification():
    notif = chat_notification("Alpha", "ch-1", "General")
    assert notif["event"] == "MESSAGE_NEW"
    assert "General" in notif["title"]
