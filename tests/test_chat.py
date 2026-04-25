"""Tests for chat persistence behavior used by sync."""

from talon.chat import send_message


def test_send_message_sets_uuid_and_sync_status(tmp_db):
    conn, _ = tmp_db
    conn.execute(
        "INSERT INTO channels (id, name, mission_id, is_dm, version, group_type) "
        "VALUES (10, '#general', NULL, 0, 1, 'allhands')"
    )
    conn.commit()

    msg = send_message(
        conn,
        10,
        1,
        "hello",
        is_urgent=True,
        grid_ref="AB1234",
        sync_status="pending",
    )

    row = conn.execute(
        "SELECT uuid, sync_status, is_urgent, grid_ref FROM messages WHERE id = ?",
        (msg.id,),
    ).fetchone()
    assert len(row[0]) == 32
    assert row[1:] == ("pending", 1, "AB1234")
