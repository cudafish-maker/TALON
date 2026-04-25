"""Server sync helper components used by ServerNetHandler."""
from __future__ import annotations

import threading
import time
import typing

import RNS

from talon.constants import LEASE_DURATION_S
from talon.network import protocol as proto
from talon.network.registry import (
    SYNC_TABLES,
    is_client_pushable,
    is_syncable,
    prepare_client_push_record_for_server_store,
)
from talon.network.sync import SyncEngine, _validated_table


class ServerUiDispatcher:
    """Dispatch server-side UI refresh notifications."""

    def __init__(self, *, notify_ui: typing.Callable[[str], None]) -> None:
        self._notify_ui = notify_ui

    def notify(self, table: str) -> None:
        self._notify_ui(table)


class ServerActiveClients:
    """Track the currently registered persistent client links."""

    def __init__(self, handler) -> None:
        self._handler = handler

    def close_all(self) -> None:
        handler = self._handler
        with handler._links_lock:
            links = list(handler._active_links.values())
            handler._active_links.clear()
        for link in links:
            handler._teardown_link(link)

    def register(self, operator_rns_hash: str, link: RNS.Link) -> int:
        handler = self._handler
        with handler._links_lock:
            old_link = handler._active_links.pop(operator_rns_hash, None)
        if old_link is not None and old_link is not link:
            handler._teardown_link(old_link)
        with handler._links_lock:
            handler._active_links[operator_rns_hash] = link
            return len(handler._active_links)

    def remove_link(self, link: RNS.Link) -> typing.Optional[str]:
        handler = self._handler
        with handler._links_lock:
            to_remove = [key for key, value in handler._active_links.items() if value is link]
            for key in to_remove:
                del handler._active_links[key]
        return to_remove[0] if to_remove else None

    def snapshot_links(self) -> list[RNS.Link]:
        with self._handler._links_lock:
            return list(self._handler._active_links.values())


class ServerRecordSerializer:
    """Serialise DB rows into wire-safe records."""

    def __init__(
        self,
        handler,
        *,
        serialise_record: typing.Callable[[dict, str, bytes], dict],
    ) -> None:
        self._handler = handler
        self._serialise_record = serialise_record

    def serialise_for_wire(self, table: str, record: dict) -> dict:
        return self._serialise_record(record, table, self._handler._db_key)


class ServerSyncRepository:
    """Read syncable server state and manage tombstones."""

    def __init__(
        self,
        handler,
        *,
        serializer: ServerRecordSerializer,
        logger,
    ) -> None:
        self._handler = handler
        self._serializer = serializer
        self._log = logger

    def operator_active(self, rns_hash: str) -> bool:
        handler = self._handler
        if not rns_hash:
            return False
        row = handler._conn.execute(
            "SELECT revoked FROM operators WHERE rns_hash = ?",
            (rns_hash,),
        ).fetchone()
        return row is not None and not bool(row[0])

    def build_delta(self, table: str, client_versions: dict) -> list[dict]:
        handler = self._handler
        if table == "operators":
            cursor = handler._conn.execute(
                "SELECT id, callsign, rns_hash, skills, profile, enrolled_at, "
                "lease_expires_at, revoked, version FROM operators WHERE id != 1"
            )
        else:
            cursor = handler._conn.execute(
                f"SELECT * FROM {_validated_table(table)}"
            )

        cols = [desc[0] for desc in cursor.description]
        delta: list[dict] = []
        for row in cursor.fetchall():
            record = dict(zip(cols, row))
            record_id = str(record.get("id", ""))
            server_ver = record.get("version", 1)
            client_ver = int(client_versions.get(record_id, 0))
            if server_ver <= client_ver:
                continue
            delta.append(self._serializer.serialise_for_wire(table, record))
        return delta

    def fetch_record(self, table: str, record_id: int) -> typing.Optional[dict]:
        handler = self._handler
        try:
            if table == "operators":
                cursor = handler._conn.execute(
                    "SELECT id, callsign, rns_hash, skills, profile, enrolled_at, "
                    "lease_expires_at, revoked, version FROM operators "
                    "WHERE id = ? AND id != 1",
                    (record_id,),
                )
            else:
                cursor = handler._conn.execute(
                    f"SELECT * FROM {_validated_table(table)} WHERE id = ?",
                    (record_id,),
                )
            cols = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()
            if row is None:
                return None
            record = dict(zip(cols, row))
            return self._serializer.serialise_for_wire(table, record)
        except Exception as exc:
            self._log.warning(
                "_fetch_record failed table=%s id=%s: %s",
                table,
                record_id,
                exc,
            )
            return None

    def get_server_id_sets(self) -> dict[str, list[int]]:
        handler = self._handler
        result: dict[str, list[int]] = {}
        for table in SYNC_TABLES:
            if not is_syncable(table):
                continue
            try:
                if table == "operators":
                    rows = handler._conn.execute(
                        "SELECT id FROM operators WHERE id != 1"
                    ).fetchall()
                else:
                    rows = handler._conn.execute(
                        f"SELECT id FROM {_validated_table(table)}"
                    ).fetchall()
                result[table] = [row[0] for row in rows]
            except Exception as exc:
                self._log.warning(
                    "_get_server_id_sets failed table=%s: %s",
                    table,
                    exc,
                )
                result[table] = []
        return result

    def get_tombstones(self, since: int) -> list[dict]:
        handler = self._handler
        try:
            rows = handler._conn.execute(
                "SELECT table_name, record_id FROM deleted_records WHERE deleted_at > ?",
                (since,),
            ).fetchall()
            return [{"table": row[0], "record_id": row[1]} for row in rows]
        except Exception as exc:
            self._log.warning("_get_tombstones failed: %s", exc)
            return []

    def gc_tombstones(self) -> None:
        cutoff = int(time.time()) - 30 * 86400
        handler = self._handler
        try:
            with handler._lock:
                handler._conn.execute(
                    "DELETE FROM deleted_records WHERE deleted_at < ?",
                    (cutoff,),
                )
                handler._conn.commit()
        except Exception as exc:
            self._log.warning("Tombstone GC failed: %s", exc)


class ServerLinkRouter:
    """Own the RNS link and packet callback wiring."""

    def __init__(self, handler, *, logger) -> None:
        self._handler = handler
        self._log = logger

    def on_link_established(self, link: RNS.Link) -> None:
        handler = self._handler
        self._log.debug("Incoming client link established")
        link.set_packet_callback(lambda data, pkt: handler._on_packet(link, data, pkt))
        link.set_resource_callback(lambda _resource: True)
        link.set_resource_concluded_callback(
            lambda resource: handler._on_resource(link, resource)
        )
        link.set_link_closed_callback(handler._on_link_closed)

    def on_resource(self, link: RNS.Link, resource) -> None:
        if resource.status == RNS.Resource.COMPLETE:
            self._handler._on_packet(link, resource.data.read(), None)
        else:
            self._log.debug(
                "Resource transfer incomplete (status=%s)",
                resource.status,
            )

    def on_link_closed(self, link: RNS.Link) -> None:
        removed = self._handler._active_clients_component.remove_link(link)
        if removed:
            self._log.debug(
                "Client link closed: removed %s from active set",
                removed[:12],
            )

    def on_packet(self, link: RNS.Link, data: bytes, packet) -> None:
        try:
            msg = proto.decode(data)
        except ValueError as exc:
            self._log.warning("Malformed packet from client: %s", exc)
            self._handler._send_error(link, str(exc))
            return

        msg_type = msg.get("type")
        if msg_type == proto.MSG_CHUNK:
            try:
                proto.validate_client_message(msg)
            except proto.ProtocolValidationError as exc:
                self._log.warning("Malformed chunk from client: %s", exc)
                self._handler._send_error(link, str(exc))
                return
            reassembled = self._handler._handle_chunk_data(msg)
            if reassembled is not None:
                self._handler._on_packet(link, reassembled, packet)
            return

        try:
            proto.validate_client_message(msg)
        except proto.ProtocolValidationError as exc:
            self._log.warning("Invalid client message: %s", exc)
            self._handler._send_error(link, str(exc))
            self._handler._teardown_link(link)
            return

        try:
            if msg_type == proto.MSG_ENROLL_REQUEST:
                self._handler._handle_enroll(link, msg)
            elif msg_type == proto.MSG_CLIENT_PUSH_RECORDS:
                self._handler._handle_client_push(link, msg)
            elif msg_type == proto.MSG_SYNC_REQUEST:
                self._handler._handle_sync(link, msg)
            elif msg_type == proto.MSG_HEARTBEAT:
                self._handler._handle_heartbeat(link, msg)
            else:
                self._log.warning(
                    "Unknown message type from client: %r",
                    msg_type,
                )
                self._handler._send_error(link, f"Unknown message type: {msg_type!r}")
                self._handler._teardown_link(link)
        except Exception as exc:
            self._log.error("Error handling %r: %s", msg_type, exc, exc_info=True)
            self._handler._send_error(link, str(exc))
            self._handler._teardown_link(link)


class ServerPushDispatcher:
    """Push changed or deleted records to connected clients."""

    def __init__(
        self,
        handler,
        *,
        active_clients: ServerActiveClients,
        smart_send: typing.Callable[[RNS.Link, bytes], None],
        logger,
    ) -> None:
        self._handler = handler
        self._active_clients = active_clients
        self._smart_send = smart_send
        self._log = logger

    def notify_change(self, table: str, record_id: int) -> None:
        handler = self._handler
        if not is_syncable(table):
            return
        with handler._push_buffer_lock:
            handler._push_buffer.setdefault(table, set()).add(record_id)
            if not handler._push_flush_scheduled:
                handler._push_flush_scheduled = True
                timer = threading.Timer(0.05, handler._flush_push_buffer)
                timer.daemon = True
                timer.start()

    def flush_push_buffer(self) -> None:
        handler = self._handler
        with handler._push_buffer_lock:
            snapshot = {table: list(ids) for table, ids in handler._push_buffer.items()}
            handler._push_buffer.clear()
            handler._push_flush_scheduled = False

        for table, ids in snapshot.items():
            links = self._active_clients.snapshot_links()
            if not links:
                continue
            for record_id in ids:
                try:
                    with handler._lock:
                        record = handler._fetch_record(table, record_id)
                    if record is None:
                        continue
                    data = proto.encode(
                        {
                            "type": proto.MSG_PUSH_UPDATE,
                            "table": table,
                            "record": record,
                        }
                    )
                    revoked_data: typing.Optional[bytes] = None
                    if table == "operators" and bool(record.get("revoked")):
                        revoked_data = proto.encode(
                            {
                                "type": proto.MSG_OPERATOR_REVOKED,
                                "operator_id": int(record_id),
                                "lease_expires_at": int(
                                    record.get("lease_expires_at") or time.time()
                                ),
                                "version": int(record.get("version") or 0),
                                "reason": "operator_revoked",
                            }
                        )
                    for link in links:
                        self._smart_send(link, data)
                        if revoked_data is not None:
                            self._smart_send(link, revoked_data)
                    self._log.debug(
                        "push_update sent: table=%s id=%s to %d client(s)",
                        table,
                        record_id,
                        len(links),
                    )
                except Exception as exc:
                    self._log.warning(
                        "notify_change failed table=%s id=%s: %s",
                        table,
                        record_id,
                        exc,
                    )

    def notify_delete(self, table: str, record_id: int) -> None:
        handler = self._handler
        if not is_syncable(table):
            return
        try:
            with handler._lock:
                handler._conn.execute(
                    "INSERT OR REPLACE INTO deleted_records "
                    "(table_name, record_id, deleted_at) VALUES (?, ?, ?)",
                    (table, record_id, int(time.time())),
                )
                handler._conn.commit()
        except Exception as exc:
            self._log.warning(
                "Failed to write tombstone table=%s id=%s: %s",
                table,
                record_id,
                exc,
            )

        links = self._active_clients.snapshot_links()
        if not links:
            return
        data = proto.encode(
            {
                "type": proto.MSG_PUSH_DELETE,
                "table": table,
                "record_id": record_id,
            }
        )
        for link in links:
            self._smart_send(link, data)
        self._log.debug(
            "push_delete sent: table=%s id=%s to %d client(s)",
            table,
            record_id,
            len(links),
        )


class ServerMessageHandlers:
    """Handle validated client sync messages."""

    def __init__(
        self,
        handler,
        *,
        active_clients: ServerActiveClients,
        ui_dispatcher: ServerUiDispatcher,
        smart_send: typing.Callable[[RNS.Link, bytes], None],
        is_hex: typing.Callable[[str], bool],
        normalise_uuid: typing.Callable[[typing.Any], typing.Optional[str]],
        logger,
    ) -> None:
        self._handler = handler
        self._active_clients = active_clients
        self._ui_dispatcher = ui_dispatcher
        self._smart_send = smart_send
        self._is_hex = is_hex
        self._normalise_uuid = normalise_uuid
        self._log = logger

    def handle_enroll(self, link: RNS.Link, msg: dict) -> None:
        token = msg.get("token", "").strip()
        callsign = msg.get("callsign", "").strip()
        rns_hash = msg.get("rns_hash", "").strip()

        if not token or not callsign or not rns_hash:
            self._smart_send(
                link,
                proto.encode(
                    {
                        "type": proto.MSG_ENROLL_RESPONSE,
                        "ok": False,
                        "operator_id": None,
                        "callsign": callsign,
                        "lease_expires_at": None,
                        "error": "enroll_request missing required fields",
                    }
                ),
            )
            self._handler._teardown_link(link)
            return
        if len(callsign) > 32:
            self._smart_send(
                link,
                proto.encode(
                    {
                        "type": proto.MSG_ENROLL_RESPONSE,
                        "ok": False,
                        "operator_id": None,
                        "callsign": callsign[:32],
                        "lease_expires_at": None,
                        "error": "callsign must be 32 characters or fewer",
                    }
                ),
            )
            self._handler._teardown_link(link)
            return
        if len(rns_hash) != 64 or not self._is_hex(rns_hash):
            self._smart_send(
                link,
                proto.encode(
                    {
                        "type": proto.MSG_ENROLL_RESPONSE,
                        "ok": False,
                        "operator_id": None,
                        "callsign": callsign,
                        "lease_expires_at": None,
                        "error": "rns_hash must be a 64-character hex string",
                    }
                ),
            )
            self._handler._teardown_link(link)
            return

        new_operator_id: typing.Optional[int] = None
        try:
            from talon.server.enrollment import create_operator

            with self._handler._lock:
                op = create_operator(self._handler._conn, callsign, rns_hash, token)
            new_operator_id = op.id
            self._smart_send(
                link,
                proto.encode(
                    {
                        "type": proto.MSG_ENROLL_RESPONSE,
                        "ok": True,
                        "operator_id": op.id,
                        "callsign": op.callsign,
                        "lease_expires_at": op.lease_expires_at,
                        "error": None,
                    }
                ),
            )
            self._log.info(
                "Operator enrolled over network: callsign=%s id=%s",
                callsign,
                op.id,
            )
        except ValueError as exc:
            self._smart_send(
                link,
                proto.encode(
                    {
                        "type": proto.MSG_ENROLL_RESPONSE,
                        "ok": False,
                        "operator_id": None,
                        "callsign": callsign,
                        "lease_expires_at": None,
                        "error": str(exc),
                    }
                ),
            )
            self._log.warning(
                "Enrollment rejected for callsign=%s: %s",
                callsign,
                exc,
            )

        self._handler._teardown_link(link)
        if new_operator_id is not None:
            self._handler.notify_change("operators", new_operator_id)

    def handle_sync(self, link: RNS.Link, msg: dict) -> None:
        handler = self._handler
        operator_rns_hash = msg.get("operator_rns_hash", "").strip()
        version_map: dict = msg.get("version_map") or {}
        try:
            last_sync_at = int(msg.get("last_sync_at", 0))
        except (TypeError, ValueError):
            self._log.warning(
                "Invalid last_sync_at from client: %r",
                msg.get("last_sync_at"),
            )
            last_sync_at = 0

        with handler._lock:
            if not handler._operator_active(operator_rns_hash):
                handler._send_error(
                    link,
                    "Operator not found or revoked",
                    code=proto.ERROR_OPERATOR_INACTIVE,
                )
                handler._teardown_link(link)
                return

            for table in SYNC_TABLES:
                if not is_syncable(table):
                    continue
                for record in handler._build_delta(table, version_map.get(table) or {}):
                    self._smart_send(
                        link,
                        proto.encode(
                            {
                                "type": proto.MSG_SYNC_RESPONSE,
                                "table": table,
                                "record": record,
                            }
                        ),
                    )

            tombstones = handler._get_tombstones(last_sync_at)
            server_id_sets = handler._get_server_id_sets()

        self._smart_send(
            link,
            proto.encode(
                {
                    "type": proto.MSG_SYNC_DONE,
                    "tombstones": tombstones,
                    "server_id_sets": server_id_sets,
                }
            ),
        )

        active_count = self._active_clients.register(operator_rns_hash, link)
        self._log.info(
            "Sync complete for %s - link registered for push (active_clients=%d)",
            operator_rns_hash[:12],
            active_count,
        )
        handler._gc_tombstones()
        handler._gc_chunk_buffers()

    def handle_heartbeat(self, link: RNS.Link, msg: dict) -> None:
        handler = self._handler
        operator_rns_hash = msg.get("operator_rns_hash", "").strip()
        now = int(time.time())
        renewed_operator_id: typing.Optional[int] = None

        with handler._lock:
            row = handler._conn.execute(
                "SELECT id, lease_expires_at, revoked FROM operators WHERE rns_hash = ?",
                (operator_rns_hash,),
            ).fetchone()

            if row is None or row[2]:
                handler._send_error(
                    link,
                    "Operator not found or revoked",
                    code=proto.ERROR_OPERATOR_INACTIVE,
                )
                return

            operator_id, lease_expires_at, _revoked = row
            if lease_expires_at - now < 3600:
                from talon.server.enrollment import renew_lease

                lease_expires_at = renew_lease(
                    handler._conn,
                    operator_id,
                    LEASE_DURATION_S,
                )
                renewed_operator_id = operator_id

        self._smart_send(
            link,
            proto.encode(
                {
                    "type": proto.MSG_HEARTBEAT_ACK,
                    "timestamp": now,
                    "lease_expires_at": lease_expires_at,
                }
            ),
        )
        if renewed_operator_id is not None:
            handler.notify_change("operators", renewed_operator_id)

    def handle_client_push(self, link: RNS.Link, msg: dict) -> None:
        handler = self._handler
        operator_rns_hash = msg.get("operator_rns_hash", "").strip()
        with handler._lock:
            if not handler._operator_active(operator_rns_hash):
                handler._send_error(
                    link,
                    "Operator not found or revoked",
                    code=proto.ERROR_OPERATOR_INACTIVE,
                )
                handler._teardown_link(link)
                return
            op_row = handler._conn.execute(
                "SELECT id FROM operators WHERE rns_hash = ?",
                (operator_rns_hash,),
            ).fetchone()
            pushing_operator_id = op_row[0] if op_row else None

        records_by_table: dict = msg.get("records") or {}
        accepted_uuids: list[str] = []
        rejected_items: list[dict] = []

        for table, records in records_by_table.items():
            if not is_client_pushable(table):
                self._log.warning(
                    "Client push for unsupported table %r - skipped",
                    table,
                )
                continue
            for record in records or []:
                if not isinstance(record, dict):
                    continue
                uuid_val = self._normalise_uuid(record.get("uuid"))
                if uuid_val is None:
                    self._log.warning(
                        "Client push rejected malformed uuid table=%s uuid=%r",
                        table,
                        record.get("uuid"),
                    )
                    continue

                with handler._lock:
                    try:
                        existing = handler._conn.execute(
                            f"SELECT id, version FROM {_validated_table(table)} "
                            "WHERE uuid = ?",
                            (uuid_val,),
                        ).fetchone()
                    except Exception as exc:
                        self._log.warning(
                            "Client push UUID lookup failed table=%s: %s",
                            table,
                            exc,
                        )
                        continue

                if existing is None:
                    clean = prepare_client_push_record_for_server_store(
                        table,
                        record,
                        uuid_value=uuid_val,
                        operator_id=pushing_operator_id,
                        db_key=handler._db_key,
                        logger=self._log,
                    )
                    if clean is None:
                        continue
                    try:
                        with handler._lock:
                            SyncEngine._upsert_record(handler._conn, table, clean)
                            new_id = handler._conn.execute(
                                f"SELECT id FROM {_validated_table(table)} WHERE uuid = ?",
                                (uuid_val,),
                            ).fetchone()
                        if new_id:
                            accepted_uuids.append(uuid_val)
                            self._log.info(
                                "Client push accepted: table=%s uuid=%s new_id=%s",
                                table,
                                uuid_val,
                                new_id[0],
                            )
                            handler.notify_change(table, new_id[0])
                            self._ui_dispatcher.notify(table)
                    except Exception as exc:
                        self._log.warning(
                            "Client push INSERT failed table=%s uuid=%s: %s",
                            table,
                            uuid_val,
                            exc,
                        )
                else:
                    server_id, _server_ver = existing
                    server_record = handler._fetch_record(table, server_id)
                    if table == "assets" and record.get("deletion_requested"):
                        try:
                            from talon.assets import request_asset_deletion

                            with handler._lock:
                                request_asset_deletion(handler._conn, server_id)
                            accepted_uuids.append(uuid_val)
                            self._log.info(
                                "Client push: deletion_requested set uuid=%s id=%s",
                                uuid_val,
                                server_id,
                            )
                            handler.notify_change(table, server_id)
                            self._ui_dispatcher.notify(table)
                        except Exception as exc:
                            self._log.warning(
                                "Client push: deletion_request failed uuid=%s: %s",
                                uuid_val,
                                exc,
                            )
                    elif table == "assets" and self._apply_existing_asset_verification(
                        uuid_val,
                        server_id,
                        record,
                        server_record,
                        pushing_operator_id,
                    ):
                        accepted_uuids.append(uuid_val)
                    else:
                        rejected_items.append(
                            {
                                "uuid": uuid_val,
                                "table": table,
                                "client_record": record,
                                "server_record": server_record,
                            }
                        )
                        self._log.debug(
                            "Client push rejected (server wins): table=%s uuid=%s",
                            table,
                            uuid_val,
                        )

        self._smart_send(
            link,
            proto.encode(
                {
                    "type": proto.MSG_PUSH_ACK,
                    "accepted": accepted_uuids,
                    "rejected": rejected_items,
                }
            ),
        )
        self._log.info(
            "push_ack sent: accepted=%d rejected=%d",
            len(accepted_uuids),
            len(rejected_items),
        )

    def _apply_existing_asset_verification(
        self,
        uuid_val: str,
        server_id: int,
        record: dict,
        server_record: typing.Optional[dict],
        pushing_operator_id: typing.Optional[int],
    ) -> bool:
        if not self._is_asset_verification_update(record, server_record):
            return False
        if pushing_operator_id is None:
            return False

        verified = bool(record.get("verified"))
        created_by = server_record.get("created_by") if isinstance(server_record, dict) else None
        if verified and created_by == pushing_operator_id:
            self._log.warning(
                "Client push rejected own-asset verification uuid=%s id=%s operator=%s",
                uuid_val,
                server_id,
                pushing_operator_id,
            )
            return False

        try:
            from talon.services.assets import verify_asset_command

            with self._handler._lock:
                verify_asset_command(
                    self._handler._conn,
                    server_id,
                    verified=verified,
                    confirmer_id=pushing_operator_id if verified else None,
                )
            self._log.info(
                "Client push: asset verification updated uuid=%s id=%s verified=%s",
                uuid_val,
                server_id,
                verified,
            )
            self._handler.notify_change("assets", server_id)
            self._ui_dispatcher.notify("assets")
            return True
        except Exception as exc:
            self._log.warning(
                "Client push: verification update failed uuid=%s id=%s: %s",
                uuid_val,
                server_id,
                exc,
            )
            return False

    @staticmethod
    def _is_asset_verification_update(
        record: dict,
        server_record: typing.Optional[dict],
    ) -> bool:
        if not isinstance(server_record, dict):
            return False

        saw_verification_change = False
        compare_keys = (set(server_record.keys()) | set(record.keys())) - {"id", "uuid"}
        for key in compare_keys:
            client_value = record.get(key)
            server_value = server_record.get(key)
            if key in {"verified", "confirmed_by"}:
                if client_value != server_value:
                    saw_verification_change = True
                continue
            if key in {"version", "sync_status"}:
                continue
            if client_value != server_value:
                return False
        return saw_verification_change
