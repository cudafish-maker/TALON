# tests/test_enrollment_flow.py
# Tests for the end-to-end enrollment flow: server token generation,
# link manager routing, client enrollment request, and lease saving.

import json
import os
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.client.auth import ClientAuth
from talon.net.link_manager import ServerLinkManager

# ======================================================================
# Server: enrollment token DB methods on TalonServer
# ======================================================================


class TestTalonServerEnrollment:
    """Tests for TalonServer enrollment token management."""

    def _make_server(self):
        """Create a minimal TalonServer with an in-memory DB."""
        from talon.server.app import TalonServer

        server = TalonServer()
        server.server_secret = b"test-secret-32-bytes-long-enough"

        # Use a real in-memory SQLite DB (not sqlcipher for tests)
        import sqlite3

        server.db = sqlite3.connect(":memory:")
        server.db.execute("""
            CREATE TABLE enrollment_tokens (
                token TEXT PRIMARY KEY,
                callsign TEXT NOT NULL,
                generated_at REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                used_by TEXT,
                used_at REAL,
                description TEXT NOT NULL DEFAULT ''
            )
        """)
        server.db.execute("""
            CREATE TABLE client_registry (
                id TEXT PRIMARY KEY,
                callsign TEXT UNIQUE NOT NULL,
                reticulum_identity TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                enrolled_at REAL NOT NULL,
                last_sync REAL,
                lease_expires_at REAL,
                revoked_at REAL,
                revoke_reason TEXT
            )
        """)
        server.db.commit()

        from talon.server.client_registry import ClientRegistry

        server.client_registry = ClientRegistry()

        return server

    def test_create_enrollment_token(self):
        """create_enrollment_token() should persist to DB."""
        server = self._make_server()
        token = server.create_enrollment_token("WOLF-1")

        assert len(token) == 32
        row = server.db.execute(
            "SELECT callsign, used FROM enrollment_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        assert row[0] == "WOLF-1"
        assert row[1] == 0

    def test_get_pending_tokens(self):
        """get_pending_tokens() returns unused tokens."""
        server = self._make_server()
        server.create_enrollment_token("ALPHA")
        server.create_enrollment_token("BRAVO")

        pending = server.get_pending_tokens()
        assert len(pending) == 2
        callsigns = {t["callsign"] for t in pending}
        assert callsigns == {"ALPHA", "BRAVO"}

    def test_get_pending_tokens_excludes_used(self):
        """get_pending_tokens() should not return used tokens."""
        server = self._make_server()
        token = server.create_enrollment_token("CHARLIE")

        # Mark as used
        server.db.execute(
            "UPDATE enrollment_tokens SET used = 1 WHERE token = ?",
            (token,),
        )
        server.db.commit()

        pending = server.get_pending_tokens()
        assert len(pending) == 0

    def test_handle_enrollment_success(self):
        """handle_enrollment() should return lease on valid token."""
        server = self._make_server()
        token = server.create_enrollment_token("DELTA")

        message = {
            "type": "enrollment_request",
            "token": token,
            "callsign": "DELTA",
            "timestamp": time.time(),
        }
        response = server.handle_enrollment("client-hash-abc", message)

        assert response["type"] == "enrollment_response"
        assert response["success"] is True
        assert "lease" in response
        assert "signature" in response
        assert response["callsign"] == "DELTA"

        # Token should now be marked used
        row = server.db.execute(
            "SELECT used, used_by FROM enrollment_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        assert row[0] == 1
        assert row[1] == "client-hash-abc"

    def test_handle_enrollment_invalid_token(self):
        """handle_enrollment() with bad token should fail."""
        server = self._make_server()

        message = {
            "type": "enrollment_request",
            "token": "0" * 32,
            "callsign": "ECHO",
            "timestamp": time.time(),
        }
        response = server.handle_enrollment("client-hash-xyz", message)

        assert response["success"] is False
        assert "Invalid" in response["error"]

    def test_handle_enrollment_used_token(self):
        """handle_enrollment() with already-used token should fail."""
        server = self._make_server()
        token = server.create_enrollment_token("FOXTROT")

        # Use it once
        msg = {
            "type": "enrollment_request",
            "token": token,
            "callsign": "FOXTROT",
            "timestamp": time.time(),
        }
        server.handle_enrollment("first-client", msg)

        # Try to use it again
        msg["callsign"] = "GOLF"
        response = server.handle_enrollment("second-client", msg)

        assert response["success"] is False
        assert "used" in response["error"].lower()

    def test_handle_enrollment_missing_fields(self):
        """handle_enrollment() with missing fields should fail."""
        server = self._make_server()

        response = server.handle_enrollment("client", {"type": "enrollment_request"})
        assert response["success"] is False
        assert "Missing" in response["error"]

    def test_handle_enrollment_registers_client(self):
        """Successful enrollment should register client in registry."""
        server = self._make_server()
        token = server.create_enrollment_token("HOTEL")

        msg = {
            "type": "enrollment_request",
            "token": token,
            "callsign": "HOTEL",
            "timestamp": time.time(),
        }
        server.handle_enrollment("hotel-hash", msg)

        # Check client registry
        client = server.client_registry.get_client("hotel-hash")
        assert client is not None
        assert client["callsign"] == "HOTEL"

        # Check DB
        row = server.db.execute(
            "SELECT callsign FROM client_registry WHERE id = ?",
            ("hotel-hash",),
        ).fetchone()
        assert row[0] == "HOTEL"


# ======================================================================
# ServerLinkManager: enrollment_request routing
# ======================================================================


class TestLinkManagerEnrollmentRouting:
    """Tests for enrollment message routing in ServerLinkManager."""

    def _make_mock_identity(self):
        mock = MagicMock()
        mock.hexhash = "abcdef1234567890"
        return mock

    def _make_mock_link(self, identity):
        mock = MagicMock()
        mock.get_remote_identity.return_value = identity
        mock.status = 2  # RNS.Link.ACTIVE
        return mock

    @patch("talon.net.link_manager.RNS")
    def test_enrollment_request_routed(self, mock_rns):
        """enrollment_request messages should go to on_enrollment callback."""
        mock_rns.Link.ACTIVE = 2
        mock_rns.Link.CLOSED = 0

        identity = self._make_mock_identity()
        slm = ServerLinkManager(identity)

        enrollment_response = {
            "type": "enrollment_response",
            "success": True,
            "lease": {"token": "abc", "expires_at": 999},
        }
        slm.on_enrollment = MagicMock(return_value=enrollment_response)
        slm.on_sync_message = MagicMock()

        # Simulate receiving an enrollment request packet
        link = self._make_mock_link(identity)
        raw = json.dumps(
            {
                "type": "enrollment_request",
                "token": "a" * 32,
                "callsign": "TEST",
            }
        ).encode("utf-8")

        slm._packet_received("client-hash", link, raw)

        slm.on_enrollment.assert_called_once()
        slm.on_sync_message.assert_not_called()

        # Should have sent the response back
        mock_rns.Packet.assert_called_once()
        mock_rns.Packet.return_value.send.assert_called_once()

    @patch("talon.net.link_manager.RNS")
    def test_sync_messages_still_routed(self, mock_rns):
        """Regular sync messages should still go to on_sync_message."""
        mock_rns.Link.ACTIVE = 2

        identity = self._make_mock_identity()
        slm = ServerLinkManager(identity)
        slm.on_enrollment = MagicMock()
        slm.on_sync_message = MagicMock(return_value={"ok": True})

        link = self._make_mock_link(identity)
        raw = json.dumps({"type": "sync_pull", "tables": []}).encode("utf-8")

        slm._packet_received("client-hash", link, raw)

        slm.on_enrollment.assert_not_called()
        slm.on_sync_message.assert_called_once()

    @patch("talon.net.link_manager.RNS")
    def test_heartbeat_still_routed(self, mock_rns):
        """Heartbeat messages should still go to on_heartbeat."""
        identity = self._make_mock_identity()
        slm = ServerLinkManager(identity)
        slm.on_enrollment = MagicMock()
        slm.on_heartbeat = MagicMock()

        link = self._make_mock_link(identity)
        raw = json.dumps({"type": "heartbeat", "ts": 123}).encode("utf-8")

        slm._packet_received("client-hash", link, raw)

        slm.on_enrollment.assert_not_called()
        slm.on_heartbeat.assert_called_once()


# ======================================================================
# ClientAuth: enrollment request building and lease saving
# ======================================================================


class TestClientAuthEnrollment:
    """Tests for client-side enrollment in ClientAuth."""

    def test_request_enrollment_format(self):
        """request_enrollment() should build a valid enrollment message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = ClientAuth(tmpdir)
            msg = auth.request_enrollment("aabbccdd" * 4, "WOLF-1")

            assert msg["type"] == "enrollment_request"
            assert msg["token"] == "aabbccdd" * 4
            assert msg["callsign"] == "WOLF-1"
            assert "timestamp" in msg

    def test_save_lease_marks_enrolled(self):
        """save_lease() should set is_enrolled and persist to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = ClientAuth(tmpdir)
            assert auth.is_enrolled is False

            lease = {
                "token": os.urandom(32).hex(),
                "issued_at": time.time(),
                "expires_at": time.time() + 86400,
                "signature": "sig123",
            }
            auth.save_lease(lease)

            assert auth.is_enrolled is True
            assert auth.is_locked is False
            assert os.path.isfile(auth.lease_path)

    def test_load_lease_after_save(self):
        """A saved lease should be loadable by a new ClientAuth instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth1 = ClientAuth(tmpdir)
            lease = {
                "token": os.urandom(32).hex(),
                "issued_at": time.time(),
                "expires_at": time.time() + 86400,
            }
            auth1.save_lease(lease)

            auth2 = ClientAuth(tmpdir)
            result = auth2.load_lease()
            assert result is True
            assert auth2.is_enrolled is True

    def test_unenrolled_state(self):
        """Fresh ClientAuth with no lease should be unenrolled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = ClientAuth(tmpdir)
            result = auth.load_lease()
            assert result is False
            assert auth.is_enrolled is False


# ======================================================================
# Integration: full enrollment round-trip (mocked RNS)
# ======================================================================


class TestEnrollmentRoundTrip:
    """Integration test: server generates token, client enrolls."""

    def test_full_enrollment_roundtrip(self):
        """Token generation -> enrollment request -> lease issued -> lease saved."""
        import sqlite3

        from talon.server.app import TalonServer
        from talon.server.client_registry import ClientRegistry

        # Set up server with in-memory DB
        server = TalonServer()
        server.server_secret = b"roundtrip-test-secret-32-bytes!!"
        server.db = sqlite3.connect(":memory:")
        server.db.execute("""
            CREATE TABLE enrollment_tokens (
                token TEXT PRIMARY KEY,
                callsign TEXT NOT NULL,
                generated_at REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                used_by TEXT,
                used_at REAL,
                description TEXT NOT NULL DEFAULT ''
            )
        """)
        server.db.execute("""
            CREATE TABLE client_registry (
                id TEXT PRIMARY KEY,
                callsign TEXT UNIQUE NOT NULL,
                reticulum_identity TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                enrolled_at REAL NOT NULL,
                last_sync REAL,
                lease_expires_at REAL,
                revoked_at REAL,
                revoke_reason TEXT
            )
        """)
        server.db.commit()
        server.client_registry = ClientRegistry()

        # Step 1: Server operator generates token
        token = server.create_enrollment_token("INDIA")

        # Step 2: Client builds enrollment request
        with tempfile.TemporaryDirectory() as tmpdir:
            client_auth = ClientAuth(tmpdir)
            msg = client_auth.request_enrollment(token, "INDIA")

            # Step 3: Server handles the request
            response = server.handle_enrollment("india-hash-123", msg)

            assert response["success"] is True
            assert response["type"] == "enrollment_response"

            # Step 4: Client saves the lease
            lease_data = {
                "token": response["lease"]["token"],
                "issued_at": response["lease"]["issued_at"],
                "expires_at": response["lease"]["expires_at"],
                "signature": response["signature"],
                "callsign": "INDIA",
            }
            client_auth.save_lease(lease_data)

            # Step 5: Verify client is enrolled
            assert client_auth.is_enrolled is True
            status = client_auth.check_lease()
            assert status["valid"] is True
            assert status["locked"] is False

            # Step 6: Verify server state
            assert len(server.get_pending_tokens()) == 0  # token was used
            client = server.client_registry.get_client("india-hash-123")
            assert client["callsign"] == "INDIA"

    def test_enrollment_then_second_attempt_fails(self):
        """After successful enrollment, same token can't be reused."""
        import sqlite3

        from talon.server.app import TalonServer
        from talon.server.client_registry import ClientRegistry

        server = TalonServer()
        server.server_secret = b"reuse-test-secret-32-bytes!!!!!!"
        server.db = sqlite3.connect(":memory:")
        server.db.execute("""
            CREATE TABLE enrollment_tokens (
                token TEXT PRIMARY KEY,
                callsign TEXT NOT NULL,
                generated_at REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                used_by TEXT,
                used_at REAL,
                description TEXT NOT NULL DEFAULT ''
            )
        """)
        server.db.execute("""
            CREATE TABLE client_registry (
                id TEXT PRIMARY KEY,
                callsign TEXT UNIQUE NOT NULL,
                reticulum_identity TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                enrolled_at REAL NOT NULL,
                last_sync REAL,
                lease_expires_at REAL,
                revoked_at REAL,
                revoke_reason TEXT
            )
        """)
        server.db.commit()
        server.client_registry = ClientRegistry()

        token = server.create_enrollment_token("JULIET")

        # First enrollment succeeds
        msg = {
            "type": "enrollment_request",
            "token": token,
            "callsign": "JULIET",
            "timestamp": time.time(),
        }
        r1 = server.handle_enrollment("juliet-hash", msg)
        assert r1["success"] is True

        # Second attempt with same token fails
        msg["callsign"] = "KILO"
        r2 = server.handle_enrollment("kilo-hash", msg)
        assert r2["success"] is False
