import pathlib
import stat
import time

import pytest

from talon.constants import DB_SCHEMA_VERSION
from talon.documents import DocumentError
from talon_core import CoreSessionError, TalonCoreSession
from talon_core.network.rns_config import (
    default_reticulum_config,
    i2pd_client_config,
    i2pd_server_config,
    reticulum_acceptance_path,
    tcp_client_config,
    tcp_server_config,
    yggdrasil_client_config,
    yggdrasil_server_config,
)

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
    result = session.unlock("OperatorPass-1", install_audit=False)

    assert result.mode == "client"
    assert calls == [("OperatorPass-1", b"0" * 16)]
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


def test_document_transfer_timeout_scales_with_size() -> None:
    import talon_core.session as session_module

    assert session_module._document_transfer_timeout_s(0) == pytest.approx(60.0)
    assert session_module._document_transfer_timeout_s(254 * 1024) == pytest.approx(314.0)
    assert session_module._document_transfer_timeout_s(50 * 1024 * 1024) == pytest.approx(1800.0)


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


def test_core_session_community_safety_commands_and_read_models(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    received = []
    session.subscribe(received.append)

    assignment_result = session.command(
        "assignments.create",
        {
            "assignment_type": "protective_detail",
            "title": "North Shelter evening support",
            "status": "active",
            "priority": "PRIORITY",
            "protected_label": "North Shelter front desk",
            "location_label": "North Shelter",
            "team_lead": "Aster",
            "checkin_interval_min": 20,
            "overdue_threshold_min": 5,
            "required_skills": ["medic", "de-escalation"],
        },
    )
    checkin_result = session.command(
        "assignments.checkin",
        {
            "assignment_id": assignment_result.assignment_id,
            "state": "need_backup",
            "note": "De-escalation support requested.",
        },
    )
    incident_result = session.command(
        "incidents.create",
        {
            "category": "community_conflict",
            "severity": "IMMEDIATE",
            "title": "Shelter support follow-up",
            "location_label": "North Shelter",
            "narrative": "Team documented a conflict and requested follow-up.",
            "actions_taken": "De-escalation support notified.",
            "follow_up_needed": True,
            "linked_assignment_id": assignment_result.assignment_id,
        },
    )

    board = session.read_model("assignments.board")
    assert board["assignments"][0].title == "North Shelter evening support"
    assert board["assignments"][0].status == "needs_support"
    assert board["recent_checkins"][0].id == checkin_result.checkin_id
    assert board["open_incidents"][0].id == incident_result.incident_id

    detail = session.read_model(
        "assignments.detail",
        {"assignment_id": assignment_result.assignment_id},
    )
    assert detail["assignment"].last_checkin_state == "need_backup"
    assert detail["checkins"][0].note == "De-escalation support requested."
    assert detail["incidents"][0].title == "Shelter support follow-up"

    incident_detail = session.read_model(
        "incidents.detail",
        {"incident_id": incident_result.incident_id},
    )
    assert incident_detail["assignment_title"] == "North Shelter evening support"

    dashboard = session.read_model("dashboard.summary")
    assert dashboard.counts["assignments"] == 1
    assert dashboard.counts["assignments_needing_support"] == 1
    assert dashboard.counts["incident_follow_ups"] == 1

    tables = {mutation.table for event in received for mutation in event.iter_records()}
    assert {"assignments", "checkins", "incidents"}.issubset(tables)

    session.close()


def test_core_session_sitrep_followups_locations_and_documents(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    received = []
    session.subscribe(received.append)

    assignment_result = session.command(
        "assignments.create",
        {
            "assignment_type": "fixed_post",
            "title": "North Gate watch",
            "status": "active",
            "priority": "PRIORITY",
            "location_label": "North Gate",
            "lat": 40.123456,
            "lon": -75.25,
        },
    )
    upload = session.command(
        "documents.upload",
        raw_filename="north-gate.txt",
        file_data=b"photo notes",
        description="North Gate attachment",
    )
    sitrep_result = session.command(
        "sitreps.create",
        {
            "level": "PRIORITY",
            "body": "Need support near North Gate.",
            "assignment_id": assignment_result.assignment_id,
            "location_label": "North Gate",
            "lat": 40.123456,
            "lon": -75.25,
            "location_precision": "exact",
            "location_source": "device",
        },
    )

    sitrep_id = sitrep_result.record_id
    listed = session.read_model("sitreps.list", {"has_location": True})
    assert listed[0][0].id == sitrep_id
    assert listed[0][0].assignment_id == assignment_result.assignment_id
    assert listed[0][0].location_label == "North Gate"
    assert listed[0][0].status == "open"

    session.command("sitreps.acknowledge", {"sitrep_id": sitrep_id})
    session.command(
        "sitreps.assign_followup",
        {"sitrep_id": sitrep_id, "assigned_to": "Team Bravo"},
    )
    session.command(
        "sitreps.link_document",
        {
            "sitrep_id": sitrep_id,
            "document_id": upload.document_id,
            "description": "Attachment reviewed.",
        },
    )
    session.command(
        "sitreps.update_status",
        {
            "sitrep_id": sitrep_id,
            "status": "closed",
            "note": "Resolved with escort handoff.",
        },
    )

    detail = session.read_model("sitreps.detail", {"sitrep_id": sitrep_id})
    assert detail["assignment_title"] == "North Gate watch"
    assert detail["sitrep"].status == "closed"
    assert detail["sitrep"].assigned_to == "Team Bravo"
    assert detail["sitrep"].disposition == "Resolved with escort handoff."
    assert [item.action for item in detail["followups"]] == [
        "acknowledged",
        "assigned",
        "document_linked",
        "status",
    ]
    assert detail["documents"][0]["document"].filename == "north-gate.txt"

    assert session.read_model("sitreps.list", {"unresolved_only": True}) == []
    assert len(session.read_model("sitreps.list", {"status_filter": "closed"})) == 1
    dashboard = session.read_model("dashboard.summary")
    assert dashboard.counts["located_sitreps"] == 1
    assert dashboard.counts["unresolved_sitreps"] == 0
    assert dashboard.counts["sitrep_followups"] == 4
    assert dashboard.counts["sitrep_documents"] == 1

    deleted = session.command("documents.delete", document_id=upload.document_id)
    assert deleted.document_id == upload.document_id
    assert session.read_model("sitreps.detail", {"sitrep_id": sitrep_id})["documents"] == []

    tables = {mutation.table for event in received for mutation in event.iter_records()}
    assert {"sitreps", "sitrep_followups", "sitrep_documents", "documents"}.issubset(
        tables
    )

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


def test_core_reticulum_config_apis_require_unlock(tmp_path: pathlib.Path) -> None:
    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()

    with pytest.raises(CoreSessionError):
        session.reticulum_config_status()
    with pytest.raises(CoreSessionError):
        session.load_reticulum_config_text()
    with pytest.raises(CoreSessionError):
        session.validate_reticulum_config_text("[reticulum]\n")
    with pytest.raises(CoreSessionError):
        session.save_reticulum_config_text("[reticulum]\n")
    with pytest.raises(CoreSessionError):
        session.import_default_reticulum_config()
    with pytest.raises(CoreSessionError):
        session.start_reticulum()

    session.close()


def test_core_reticulum_missing_config_returns_default_after_unlock(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    status = session.reticulum_config_status()
    text = session.load_reticulum_config_text()

    assert status.exists is False
    assert status.valid is True
    assert status.accepted is False
    assert status.needs_setup is True
    assert "[reticulum]" in text
    assert "share_instance = No" in text
    assert "TALON AutoInterface" in text
    with pytest.raises(CoreSessionError, match="Reticulum config is missing"):
        session.start_reticulum()

    session.close()


def test_core_reticulum_existing_unaccepted_config_still_needs_setup(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)
    session.paths.rns_config_dir.mkdir(parents=True)
    config_file = session.paths.rns_config_dir / "config"
    config_file.write_text(default_reticulum_config("server"), encoding="utf-8")

    status = session.reticulum_config_status()

    assert status.exists is True
    assert status.valid is True
    assert status.accepted is False
    assert status.needs_setup is True
    with pytest.raises(CoreSessionError, match="has not been accepted"):
        session.start_reticulum()

    session.save_reticulum_config_text(session.load_reticulum_config_text())
    accepted = session.reticulum_config_status()

    assert accepted.accepted is True
    assert accepted.needs_setup is False
    assert reticulum_acceptance_path(session.paths.rns_config_dir).is_file()

    session.close()


def test_core_reticulum_invalid_config_returns_blocking_errors(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    validation = session.validate_reticulum_config_text("[reticulum\n  broken = yes\n")

    assert validation.valid is False
    assert validation.errors

    session.close()


def test_core_reticulum_save_writes_private_permissions_and_backup(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)
    first_text = session.load_reticulum_config_text()

    first = session.save_reticulum_config_text(first_text)
    second_text = first_text.replace("loglevel = 4", "loglevel = 3")
    second = session.save_reticulum_config_text(second_text)

    assert first.path == session.paths.rns_config_dir / "config"
    assert first.backup_path is None
    assert second.backup_path is not None
    assert second.backup_path.read_text(encoding="utf-8") == first_text
    assert session.reticulum_config_status().accepted is True
    assert stat.S_IMODE(session.paths.rns_config_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(first.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(second.backup_path.stat().st_mode) == 0o600
    acceptance_mode = reticulum_acceptance_path(session.paths.rns_config_dir).stat().st_mode
    assert stat.S_IMODE(acceptance_mode) == 0o600

    session.close()


def test_core_reticulum_import_default_requires_explicit_unlocked_call(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    default_dir = home / ".reticulum"
    default_dir.mkdir(parents=True)
    default_text = (
        "[reticulum]\n"
        "  enable_transport = False\n"
        "  share_instance = No\n"
        "\n"
        "[interfaces]\n"
        "  [[Default TCP Client]]\n"
        "    type = TCPClientInterface\n"
        "    enabled = Yes\n"
        "    target_host = server.lan\n"
        "    target_port = 4242\n"
    )
    (default_dir / "config").write_text(default_text, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    with pytest.raises(CoreSessionError):
        session.import_default_reticulum_config()

    session.unlock_with_key(TEST_KEY)
    result = session.import_default_reticulum_config()

    assert result.path.read_text(encoding="utf-8") == default_text
    assert "server.lan" in session.load_reticulum_config_text()
    assert session.reticulum_config_status().accepted is True

    session.close()


def test_core_reticulum_validation_reports_talon_warnings(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    risky = (
        "[reticulum]\n"
        "  enable_transport = False\n"
        "  share_instance = Yes\n"
        "\n"
        "[interfaces]\n"
        "  [[Local Server]]\n"
        "    type = TCPServerInterface\n"
        "    enabled = Yes\n"
        "    listen_ip = 127.0.0.1\n"
        "    listen_port = 4242\n"
        "  [[Local Client]]\n"
        "    type = TCPClientInterface\n"
        "    enabled = Yes\n"
        "    target_host = localhost\n"
    )
    warnings = "\n".join(session.validate_reticulum_config_text(risky).warnings)

    assert "share_instance is enabled" in warnings
    assert "Server transport is disabled" in warnings
    assert "Local Server listens on localhost" in warnings
    assert "Local Client targets localhost" in warnings
    assert "Local Client has no target_port" in warnings

    no_enabled = (
        "[reticulum]\n"
        "  enable_transport = True\n"
        "  share_instance = No\n"
        "\n"
        "[interfaces]\n"
        "  [[Disabled Auto]]\n"
        "    type = AutoInterface\n"
        "    enabled = No\n"
    )
    no_enabled_warnings = "\n".join(
        session.validate_reticulum_config_text(no_enabled).warnings
    )
    assert "No enabled Reticulum interfaces" in no_enabled_warnings

    missing_target = (
        "[reticulum]\n"
        "  enable_transport = False\n"
        "  share_instance = No\n"
        "\n"
        "[interfaces]\n"
        "  [[Missing Target]]\n"
        "    type = TCPClientInterface\n"
        "    enabled = Yes\n"
        "    target_port = 4242\n"
    )
    missing_target_warnings = "\n".join(
        session.validate_reticulum_config_text(missing_target).warnings
    )
    assert "Missing Target has no target_host" in missing_target_warnings

    session.close()


def test_core_reticulum_yggdrasil_and_i2pd_templates_validate(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    yggdrasil_server = yggdrasil_server_config(device="tun0", port=4343)
    assert "TALON Yggdrasil Server" in yggdrasil_server
    assert "type = TCPServerInterface" in yggdrasil_server
    assert "device = tun0" in yggdrasil_server
    assert session.validate_reticulum_config_text(yggdrasil_server).valid is True

    i2pd_server = i2pd_server_config()
    assert "TALON i2pd Server" in i2pd_server
    assert "type = I2PInterface" in i2pd_server
    assert session.validate_reticulum_config_text(i2pd_server).valid is True
    session.close()

    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    yggdrasil_client = yggdrasil_client_config(
        "201:5d78:af73:5caf:a4de:a79f:3278:71e5",
        port=4343,
    )
    assert "TALON Yggdrasil Client" in yggdrasil_client
    assert (
        "target_host = 201:5d78:af73:5caf:a4de:a79f:3278:71e5"
        in yggdrasil_client
    )
    assert session.validate_reticulum_config_text(yggdrasil_client).valid is True

    i2pd_client = i2pd_client_config(
        "5urvjicpzi7q3ybztsef4i5ow2aq4soktfj7zedz53s47r54jnqq.b32.i2p"
    )
    assert "TALON i2pd Client" in i2pd_client
    assert (
        "peers = 5urvjicpzi7q3ybztsef4i5ow2aq4soktfj7zedz53s47r54jnqq.b32.i2p"
        in i2pd_client
    )
    assert session.validate_reticulum_config_text(i2pd_client).valid is True

    session.close()


def test_core_sync_status_reports_redacted_network_method(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "client")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)

    session.save_reticulum_config_text(tcp_client_config("203.0.113.44", port=4242))
    direct_tcp = session.read_model("sync.status")
    assert direct_tcp.network_method == "tcp"
    assert direct_tcp.network_method_label == "TCP"
    assert direct_tcp.network_method_exposes_ip is True
    assert direct_tcp.network_method_warning == "direct_tcp_ip_exposure"
    assert "203.0.113.44" not in direct_tcp.network_method_label

    session.save_reticulum_config_text(
        yggdrasil_client_config("201:5d78:af73:5caf:a4de:a79f:3278:71e5")
    )
    yggdrasil = session.read_model("sync.status")
    assert yggdrasil.network_method == "yggdrasil"
    assert yggdrasil.network_method_label == "Yggdrasil"
    assert yggdrasil.network_method_exposes_ip is False
    assert yggdrasil.network_method_warning is None
    assert "201:5d78" not in yggdrasil.network_method_label

    session.save_reticulum_config_text(
        i2pd_client_config(
            "5urvjicpzi7q3ybztsef4i5ow2aq4soktfj7zedz53s47r54jnqq.b32.i2p"
        )
    )
    i2p = session.read_model("sync.status")
    assert i2p.network_method == "i2p"
    assert i2p.network_method_label == "I2P"
    assert i2p.network_method_exposes_ip is False

    session.close()


def test_core_sync_status_reports_server_tcp_warning_without_addresses(
    tmp_path: pathlib.Path,
) -> None:
    config_path = _write_config(tmp_path, "server")
    session = TalonCoreSession(config_path=config_path).start()
    session.unlock_with_key(TEST_KEY)
    session.save_reticulum_config_text(tcp_server_config(listen_ip="0.0.0.0", port=4242))

    sync_status = session.read_model("sync.status")

    assert sync_status.network_method == "tcp"
    assert sync_status.network_method_label == "TCP"
    assert sync_status.network_method_exposes_ip is True
    assert "0.0.0.0" not in sync_status.network_method_label

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
