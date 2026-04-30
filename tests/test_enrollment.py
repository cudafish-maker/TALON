"""Tests for talon.server.enrollment."""
import time

import pytest

from talon.server.enrollment import (
    create_operator,
    generate_enrollment_token,
    list_pending_tokens,
    renew_lease,
)
from talon_core.server.enrollment import _stored_token_key


class TestGenerateEnrollmentToken:
    def test_returns_hex_string(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        assert isinstance(token, str)
        # os.urandom(32).hex() → 64 hex chars
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_tokens_are_unique(self, tmp_db):
        conn, _ = tmp_db
        t1 = generate_enrollment_token(conn)
        t2 = generate_enrollment_token(conn)
        assert t1 != t2

    def test_token_persisted(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        row = conn.execute(
            "SELECT token, token_preview FROM enrollment_tokens WHERE token = ?",
            (_stored_token_key(token),),
        ).fetchone()
        assert row is not None
        assert row[0] != token
        assert row[1] == f"{token[:8]}...{token[-8:]}"

    def test_token_has_future_expiry(self, tmp_db):
        conn, _ = tmp_db
        before = int(time.time())
        generate_enrollment_token(conn)
        row = conn.execute(
            "SELECT expires_at FROM enrollment_tokens ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert row[0] > before


class TestListPendingTokens:
    def test_returns_generated_token(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        pending = list_pending_tokens(conn)
        tokens = [t.token for t in pending]
        assert token not in tokens
        assert f"{token[:8]}...{token[-8:]}" in tokens

    def test_excludes_consumed_token(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        create_operator(conn, "W1AW", "aabbcc", token)
        pending = [t.token for t in list_pending_tokens(conn)]
        assert token not in pending

    def test_excludes_expired_token(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        # Back-date expiry to the past
        conn.execute(
            "UPDATE enrollment_tokens SET expires_at = 1 WHERE token = ?",
            (_stored_token_key(token),),
        )
        conn.commit()
        pending = [t.token for t in list_pending_tokens(conn)]
        assert token not in pending


class TestCreateOperator:
    def test_successful_enrollment(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        op = create_operator(conn, "N0CALL", "deadbeef", token)
        assert op.callsign == "N0CALL"
        assert op.rns_hash == "deadbeef"
        assert op.revoked is False
        assert op.id is not None

    def test_token_marked_used(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        create_operator(conn, "N0CALL", "deadbeef", token)
        row = conn.execute(
            "SELECT used_at FROM enrollment_tokens WHERE token = ?",
            (_stored_token_key(token),),
        ).fetchone()
        assert row[0] is not None

    def test_token_links_to_operator(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        op = create_operator(conn, "N0CALL", "deadbeef", token)
        row = conn.execute(
            "SELECT operator_id FROM enrollment_tokens WHERE token = ?",
            (_stored_token_key(token),),
        ).fetchone()
        assert row[0] == op.id

    def test_invalid_token_raises(self, tmp_db):
        conn, _ = tmp_db
        with pytest.raises(ValueError, match="not found"):
            create_operator(conn, "N0CALL", "deadbeef", "notavalidtoken")

    def test_already_used_token_raises(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        create_operator(conn, "N0CALL", "aabbcc", token)
        with pytest.raises(ValueError, match="already been used"):
            create_operator(conn, "N1NEW", "ddeeff", token)

    def test_expired_token_raises(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        conn.execute(
            "UPDATE enrollment_tokens SET expires_at = 1 WHERE token = ?",
            (_stored_token_key(token),),
        )
        conn.commit()
        with pytest.raises(ValueError, match="expired"):
            create_operator(conn, "N0CALL", "deadbeef", token)

    def test_duplicate_callsign_raises(self, tmp_db):
        conn, _ = tmp_db
        t1 = generate_enrollment_token(conn)
        t2 = generate_enrollment_token(conn)
        create_operator(conn, "N0CALL", "aabbcc", t1)
        with pytest.raises(ValueError, match="Could not create operator"):
            create_operator(conn, "N0CALL", "ddeeff", t2)

    def test_duplicate_rns_hash_raises(self, tmp_db):
        conn, _ = tmp_db
        t1 = generate_enrollment_token(conn)
        t2 = generate_enrollment_token(conn)
        create_operator(conn, "N0CALL", "aabbcc", t1)
        with pytest.raises(ValueError, match="Could not create operator"):
            create_operator(conn, "N1NEW", "aabbcc", t2)


class TestRenewLease:
    def test_returns_future_timestamp(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        op = create_operator(conn, "N0CALL", "deadbeef", token)
        before = int(time.time())
        new_expiry = renew_lease(conn, op.id, 3600)
        assert new_expiry > before

    def test_lease_persisted(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        op = create_operator(conn, "N0CALL", "deadbeef", token)
        new_expiry = renew_lease(conn, op.id, 3600)
        row = conn.execute(
            "SELECT lease_expires_at FROM operators WHERE id = ?", (op.id,)
        ).fetchone()
        assert row[0] == new_expiry

    def test_renew_lease_bumps_operator_version(self, tmp_db):
        conn, _ = tmp_db
        token = generate_enrollment_token(conn)
        op = create_operator(conn, "N0CALL", "deadbeef", token)
        before = conn.execute(
            "SELECT version FROM operators WHERE id = ?", (op.id,)
        ).fetchone()[0]
        renew_lease(conn, op.id, 3600)
        after = conn.execute(
            "SELECT version FROM operators WHERE id = ?", (op.id,)
        ).fetchone()[0]
        assert after == before + 1
