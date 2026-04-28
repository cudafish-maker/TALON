import pathlib
import time

import pytest

from talon.constants import DB_SCHEMA_VERSION
from talon.documents import DocumentError
from talon_core import CoreSessionError, TalonCoreSession

TEST_KEY = bytes(range(32))


def _write_config(tmp_path: pathlib.Path, mode: str) -> pathlib.Path:
    data_dir = tmp_path / f"{mode}-data"
    rns_dir = tmp_path / f"{mode}-rns"
    documents_dir = tmp_path / f"{mode}-documents"
    config_path = tmp_path / f"{mode}.ini"
    config_path.write_text(
        "\n".join(
            [
                "[talon]",
                f"mode = {mode}",
                "",
                "[paths]",
                f"data_dir = {data_dir}",
                f"rns_config_dir = {rns_dir}",
                "",
                "[documents]",
                f"storage_path = {documents_dir}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def test_core_session_starts_unlocks_and_closes_client(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(tmp_path, "client")

    session = TalonCoreSession(config_path=config_path).start()

    assert session.mode == "client"
    assert session.paths.data_dir == tmp_path / "client-data"
    assert session.paths.rns_config_dir == tmp_path / "client-rns"
    assert session.paths.document_storage_path == tmp_path / "client-documents"

    result = session.unlock_with_key(TEST_KEY)

    assert result.mode == "client"
    assert result.operator_id is None
    assert session.is_unlocked is True

    status = session.read_model("session")
    assert status["mode"] == "client"
    assert status["unlocked"] is True
    assert status["operator_id"] is None
    assert status["sync_started"] is False

    assert session.read_model("operators") == []
    row = session.conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    assert int(row[0]) == DB_SCHEMA_VERSION

    session.close()

    assert session.conn is None
    assert session.is_unlocked is False
    assert session.read_model("session")["unlocked"] is False
    with pytest.raises(CoreSessionError):
        session.read_model("operators")


def test_core_session_unlock_derives_key_from_passphrase(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_config(tmp_path, "client")
    calls: list[tuple[str, bytes]] = []

    import talon_core.session as session_module

    monkeypatch.setattr(
        session_module,
        "load_or_create_salt",
        lambda path: b"0" * 16,
    )

    def _fake_derive(passphrase: str, salt: bytes) -> bytes:
        calls.append((passphrase, salt))
        return TEST_KEY

    monkeypatch.setattr(session_module, "derive_key", _fake_derive)

    session = TalonCoreSession(config_path=config_path).start()
    result = session.unlock("operator-passphrase", install_audit=False)

    assert result.mode == "client"
    assert calls == [("operator-passphrase", b"0" * 16)]
    assert session.is_unlocked is True

    session.close()


def test_core_session_dispatches_asset_command_events(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    received = []
    unsubscribe = session.subscribe(received.append)

    result = session.command(
        "assets.create",
        category="cache",
        label="North Cache",
        description="Dry box",
        lat=40.0,
        lon=-75.0,
    )

    assert result.asset_id > 0
    assert len(received) == 1
    assert received[0].kind == "record_changed"
    assert received[0].table == "assets"
    assert received[0].record_id == result.asset_id

    row = session.conn.execute(
        "SELECT created_by, label FROM assets WHERE id = ?",
        (result.asset_id,),
    ).fetchone()
    assert row == (1, "North Cache")

    unsubscribe()
    session.command(
        "assets.create",
        category="cache",
        label="South Cache",
        description="",
    )
    assert len(received) == 1

    session.close()


def test_core_session_rejects_unknown_command_and_read_model(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    with pytest.raises(KeyError):
        session.command("unknown.command")
    with pytest.raises(KeyError):
        session.read_model("unknown")

    session.close()


def test_core_session_context_manager_starts_when_cfg_is_supplied(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "client")
    from talon.config import load_config

    with TalonCoreSession(cfg=load_config(config_path)) as session:
        assert session.mode == "client"
        assert session.paths.data_dir == tmp_path / "client-data"


def test_core_session_document_commands_and_read_models(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    received = []
    session.subscribe(received.append)

    upload = session.command(
        "documents.upload",
        raw_filename="../report.txt",
        file_data=b"field report",
        description="daily report",
    )

    assert upload.document_id > 0
    assert upload.document.filename == "report.txt"
    assert received[-1].kind == "record_changed"
    assert received[-1].table == "documents"
    assert received[-1].record_id == upload.document_id

    items = session.read_model("documents.list")
    assert len(items) == 1
    assert items[0].document.id == upload.document_id
    assert items[0].uploader_callsign == "SERVER"

    detail = session.read_model("documents.detail", {"document_id": upload.document_id})
    assert detail.document.description == "daily report"
    assert detail.uploader_callsign == "SERVER"

    downloaded = session.command("documents.download", document_id=upload.document_id)
    assert downloaded.document.id == upload.document_id
    assert downloaded.plaintext == b"field report"

    deleted = session.command("documents.delete", document_id=upload.document_id)
    assert deleted.document_id == upload.document_id
    assert deleted.document.filename == "report.txt"
    assert received[-1].kind == "record_deleted"
    assert received[-1].table == "documents"
    assert session.read_model("documents.list") == []

    session.close()


def test_core_session_document_delete_is_server_only(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    with pytest.raises(CoreSessionError):
        session.command("documents.delete", document_id=1)

    with pytest.raises(DocumentError):
        session.command("documents.download", document_id=1)

    session.close()


def test_core_session_phase1_domain_boundary(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    received = []
    session.subscribe(received.append)

    asset_result = session.command(
        "assets.create",
        category="cache",
        label="Medical Cache",
        description="Bandages and water",
        lat=40.5,
        lon=-75.5,
    )
    assets = session.read_model("assets.list")
    assert [asset.label for asset in assets] == ["Medical Cache"]

    sitrep_result = session.command(
        "sitreps.create",
        level="ROUTINE",
        body="Cache inventoried",
        asset_id=asset_result.asset_id,
    )
    sitreps = session.read_model("sitreps.list")
    assert sitreps[0][0].id == sitrep_result.record_id
    assert sitreps[0][0].body == b"Cache inventoried"
    assert sitreps[0][2] == "Medical Cache"

    session.command("chat.ensure_defaults")
    channel_result = session.command("chat.create_channel", name="ops")
    message_result = session.command(
        "chat.send_message",
        channel_id=channel_result.channel.id,
        body="Urgent supply pickup",
        is_urgent=True,
        grid_ref="18T WL 000 000",
    )
    messages = session.read_model(
        "chat.messages",
        {"channel_id": channel_result.channel.id},
    )
    assert messages[0][0].id == message_result.message.id
    assert messages[0][1] == "SERVER"
    alerts = session.read_model("chat.alerts")
    assert alerts[0]["text"] == "SERVER: Urgent supply pickup"
    assert session.read_model("chat.current_operator")["callsign"] == "SERVER"

    mission_result = session.command(
        "missions.create",
        title="Cache Sweep",
        description="Check medical cache",
        asset_ids=[asset_result.asset_id],
    )
    missions = session.read_model("missions.list")
    assert missions[0].id == mission_result.mission.id
    assert missions[0].status == "pending_approval"

    approval = session.read_model(
        "missions.approval_context",
        {"mission_id": mission_result.mission.id},
    )
    assert approval["creator_callsign"] == "SERVER"
    assert approval["requested_ids"] == {asset_result.asset_id}

    session.command(
        "missions.approve",
        mission_id=mission_result.mission.id,
        asset_ids=[asset_result.asset_id],
    )
    detail = session.read_model(
        "missions.detail",
        {"mission_id": mission_result.mission.id},
    )
    assert detail["mission"].title == "Cache Sweep"
    assert detail["channel_name"].startswith("#mission-cache-sweep")
    assert [asset.id for asset in detail["assets"]] == [asset_result.asset_id]
    assert detail["sitreps"] == []

    map_context = session.read_model("map.context")
    assert [asset.id for asset in map_context.assets] == [asset_result.asset_id]
    assert [mission.id for mission in map_context.missions] == [mission_result.mission.id]

    session.command("settings.set_audio_enabled", enabled=True)
    assert session.read_model("settings.audio_enabled") is True
    session.command("settings.set_meta", key="global_font_scale", value=1.3)
    assert session.read_model("settings.font_scale") == 1.3

    tables = [event.table for event in received if event.table]
    assert "assets" in tables
    assert "sitreps" in tables
    assert "messages" in tables
    assert "missions" in tables

    session.close()


def test_core_session_server_chat_message_notifies_sync_push(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    changed: list[tuple[str, int]] = []

    class _NetHandler:
        def notify_change(self, table: str, record_id: int) -> None:
            changed.append((table, record_id))

        def notify_delete(self, table: str, record_id: int) -> None:
            raise AssertionError("delete notification was not expected")

        def stop(self) -> None:
            return None

    session._net_handler = _NetHandler()
    session.command("chat.ensure_defaults")
    channel_result = session.command("chat.create_channel", name="ops")

    message_result = session.command(
        "chat.send_message",
        channel_id=channel_result.channel.id,
        body="Server relay check",
    )

    assert ("channels", channel_result.channel.id) in changed
    assert ("messages", message_result.message.id) in changed

    session.close()


def test_core_session_server_commands_flush_push_updates_without_timer(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from talon.network import protocol as proto
    from talon.server import net_components, net_handler

    class _NoOpTimer:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def start(self) -> None:
            return None

    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    sent: list[dict] = []
    monkeypatch.setattr(
        net_handler,
        "_smart_send",
        lambda _link, data: sent.append(proto.decode(data)),
    )
    monkeypatch.setattr(net_components.threading, "Timer", _NoOpTimer)
    handler = net_handler.ServerNetHandler(
        session.conn,
        session.cfg,
        TEST_KEY,
    )
    handler._active_links["client"] = object()
    session._net_handler = handler

    session.command("chat.ensure_defaults")
    channel_result = session.command("chat.create_channel", name="ops")
    message_result = session.command(
        "chat.send_message",
        channel_id=channel_result.channel.id,
        body="Server push update",
    )

    updates = [msg for msg in sent if msg["type"] == proto.MSG_PUSH_UPDATE]
    assert any(
        msg["table"] == "messages"
        and msg["record"]["id"] == message_result.message.id
        for msg in updates
    )

    session.close()


def test_core_session_client_chat_message_enters_outbox(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)
    session.conn.execute(
        "INSERT INTO operators "
        "(id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (8, 'CHATTER', ?, '[]', '{}', 1000, 9999999999, 0)",
        ("c" * 64,),
    )
    session.conn.execute(
        "INSERT INTO channels (id, name, mission_id, is_dm, version, group_type) "
        "VALUES (10, '#general', NULL, 0, 1, 'allhands')"
    )
    session.conn.commit()
    session._operator_id = 8
    pushed: list[tuple[str, int]] = []

    class _ClientSync:
        def push_record_pending(self, table: str, record_id: int) -> None:
            pushed.append((table, record_id))

        def stop(self) -> None:
            return None

    session._client_sync = _ClientSync()

    result = session.command(
        "chat.send_message",
        channel_id=10,
        body="Client relay check",
    )

    row = session.conn.execute(
        "SELECT sender_id, sync_status FROM messages WHERE id = ?",
        (result.message.id,),
    ).fetchone()
    assert row == (8, "pending")
    assert pushed == [("messages", result.message.id)]

    session.close()


def test_core_session_network_client_notify_publishes_refresh_event(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)
    received = []
    session.subscribe(received.append)

    session._notify_client_ui("assets", badge=False)

    assert len(received) == 1
    assert received[0].kind == "ui_refresh_requested"
    assert received[0].ui_targets == frozenset({"assets", "main"})

    session.close()


def test_core_session_network_operator_notify_refreshes_chat(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)
    received = []
    session.subscribe(received.append)

    session._notify_client_ui("operators", badge=False)

    assert len(received) == 1
    assert received[0].kind == "ui_refresh_requested"
    assert received[0].ui_targets == frozenset({"operators", "clients", "chat"})

    session.close()


def test_core_session_network_notify_keeps_legacy_callback_authoritative(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "client")
    callback_calls = []
    session = TalonCoreSession(
        config_path=config_path,
        on_data_pushed=lambda table, *, badge=True: callback_calls.append(
            (table, badge)
        ),
    ).start()
    session.unlock_with_key(TEST_KEY)
    received = []
    session.subscribe(received.append)

    session._notify_client_ui("assets", badge=False)

    assert callback_calls == [("assets", False)]
    assert received == []

    session.close()


def test_core_session_server_admin_boundary(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    token_result = session.command("enrollment.generate_token")

    assert len(token_result.token) == 64
    assert token_result.combined == token_result.token
    assert session.read_model("enrollment.server_hash") == ""

    pending = session.read_model("enrollment.pending_tokens")
    assert [token.token for token in pending] == [token_result.token]

    session.close()


def test_core_session_dashboard_and_sync_status_read_models(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()

    locked_dashboard = session.read_model("dashboard.summary")
    assert locked_dashboard.unlocked is False
    assert locked_dashboard.counts == {}
    assert locked_dashboard.sync.connection_state == "server-stopped"

    session.unlock_with_key(TEST_KEY)
    asset_result = session.command(
        "assets.create",
        category="cache",
        label="Pending Cache",
        description="",
        sync_status="pending",
    )
    session.command(
        "sitreps.create",
        level="FLASH",
        body="High priority update",
        asset_id=asset_result.asset_id,
    )

    dashboard = session.read_model("dashboard.summary")
    assert dashboard.unlocked is True
    assert dashboard.mode == "server"
    assert dashboard.counts["assets"] == 1
    assert dashboard.counts["sitreps"] == 1
    assert dashboard.counts["flash_sitreps"] == 1
    assert dashboard.sync.pending_outbox_by_table["assets"] == 1
    assert dashboard.sync.pending_outbox_count == 1

    sync_status = session.read_model("sync.status")
    assert sync_status.connection_state == "server-stopped"
    assert sync_status.reticulum_started is False
    assert sync_status.sync_started is False
    assert sync_status.pending_outbox_count == 1
    assert sync_status.active_client_count == 0

    session.close()


def test_core_session_sync_status_uses_runtime_manager_snapshots(
    tmp_path: pathlib.Path,
) -> None:
    class FakeClientSync:
        def status(self):
            return {
                "started": True,
                "connected": True,
                "enrolled": True,
                "operator_id": 42,
                "last_sync_at": 12345,
            }

        def stop(self):
            pass

    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)
    session._client_sync = FakeClientSync()

    sync_status = session.read_model("sync.status")
    assert sync_status.connection_state == "client-connected"
    assert sync_status.connected is True
    assert sync_status.sync_started is True
    assert sync_status.last_sync_at == 12345

    session.close()


def test_core_session_blocks_client_self_verification(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    now = int(time.time())
    session.conn.execute(
        "INSERT INTO operators "
        "(callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (?, ?, '[]', '{}', ?, ?, 0)",
        ("ALPHA", "abc123", now, now + 3600),
    )
    session.conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('my_operator_id', '2')"
    )
    session.conn.commit()

    created = session.command(
        "assets.create",
        category="cache",
        label="Client Cache",
        description="",
    )

    with pytest.raises(ValueError, match="cannot verify their own"):
        session.command(
            "assets.verify",
            asset_id=created.asset_id,
            verified=True,
        )

    with pytest.raises(CoreSessionError):
        session.command("sitreps.delete", sitrep_id=1)
    with pytest.raises(CoreSessionError):
        session.command("missions.approve", mission_id=1)
    with pytest.raises(CoreSessionError):
        session.command("chat.delete_message", message_id=1)

    session.close()
