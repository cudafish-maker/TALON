"""Tests for talon.server.revocation."""

from talon.server.revocation import revoke_operator


def test_revoke_operator_bumps_version(tmp_db):
    conn, _ = tmp_db
    conn.execute(
        "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (70, 'REVOKE', ?, '[]', '{}', 1000, 9999999999, 0)",
        ("c" * 64,),
    )
    conn.commit()
    before = conn.execute("SELECT version FROM operators WHERE id = 70").fetchone()[0]

    revoke_operator(conn, 70)

    row = conn.execute(
        "SELECT revoked, rns_hash, version FROM operators WHERE id = 70"
    ).fetchone()
    assert row == (1, "", before + 1)
