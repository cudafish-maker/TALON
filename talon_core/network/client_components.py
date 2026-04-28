"""Client sync helper components used by ClientSyncManager."""
from __future__ import annotations

import json
import threading
import time
import typing

import RNS

from talon_core.constants import HEARTBEAT_BROADBAND_S, HEARTBEAT_LORA_S
from talon_core.network import protocol as proto
from talon_core.network.registry import (
    OFFLINE_TABLES,
    TOMBSTONE_APPLY_ORDER,
    TOMBSTONE_ORDER_MAP,
    is_offline_creatable,
    is_syncable,
    prepare_client_outbox_record,
    prepare_server_record_for_client_store,
    predelete_sql,
)
from talon_core.network.sync import SyncEngine, _validated_table


class ClientUiDispatcher:
    """Dispatch table-level refresh notifications back to the Kivy app."""

    def __init__(
        self,
        *,
        notify_ui: typing.Callable[..., None],
    ) -> None:
        self._notify_ui = notify_ui

    def notify(self, table: str, *, badge: bool = True) -> None:
        self._notify_ui(table, badge=badge)


class ClientDocumentTransfers:
    """Request, receive, cache, and reuse server-hosted documents."""

    def __init__(
        self,
        manager,
        *,
        smart_send: typing.Callable[[RNS.Link, bytes], None],
        logger,
    ) -> None:
        self._manager = manager
        self._smart_send = smart_send
        self._log = logger

    def fetch_document(
        self,
        document_id: int,
        *,
        timeout_s: float = 60.0,
    ) -> bytes:
        from talon_core.config import get_document_storage_path
        from talon_core.documents import (
            DocumentError,
            DocumentIntegrityError,
            download_document,
            evict_document_cache,
        )

        manager = self._manager
        try:
            doc_id = int(document_id)
        except (TypeError, ValueError) as exc:
            raise DocumentError(f"Invalid document id: {document_id!r}") from exc

        storage_root = get_document_storage_path(manager._cfg)
        local_error: typing.Optional[Exception] = None

        with manager._lock:
            try:
                _, plaintext = download_document(
                    manager._conn,
                    manager._db_key,
                    storage_root,
                    doc_id,
                    downloader_id=manager._operator_id or 0,
                )
                return plaintext
            except DocumentIntegrityError as exc:
                local_error = exc
                try:
                    evict_document_cache(
                        manager._conn,
                        storage_root,
                        doc_id,
                        clear_db_path=True,
                        commit=True,
                    )
                except Exception as purge_exc:
                    self._log.warning(
                        "Could not purge corrupt cached document id=%s: %s",
                        doc_id,
                        purge_exc,
                    )
            except DocumentError as exc:
                local_error = exc

        link = manager._link
        if link is None:
            if isinstance(local_error, DocumentIntegrityError):
                raise local_error
            raise DocumentError(
                "Document is not cached locally and no active broadband sync link is available."
            )

        with manager._document_request_lock:
            state = manager._pending_document_requests.get(doc_id)
            if state is None:
                state = {
                    "event": threading.Event(),
                    "payload": None,
                    "error": None,
                }
                manager._pending_document_requests[doc_id] = state
                should_send = True
            else:
                should_send = False

        if should_send:
            my_rns_hash = manager._identity.hash.hex() if manager._identity else ""
            try:
                self._smart_send(
                    link,
                    proto.encode(
                        {
                            "type": proto.MSG_DOCUMENT_REQUEST,
                            "operator_rns_hash": my_rns_hash,
                            "document_id": doc_id,
                        }
                    ),
                )
                self._log.info("Requested document from server: id=%s", doc_id)
            except Exception as exc:
                self._resolve_request(
                    doc_id,
                    error=f"Could not request document download: {exc}",
                )

        if not state["event"].wait(timeout=timeout_s):
            raise DocumentError(
                "Timed out waiting for the server to transfer the document."
            )

        with manager._document_request_lock:
            current = manager._pending_document_requests.get(doc_id)
            if current is state:
                del manager._pending_document_requests[doc_id]

        error = state.get("error")
        if error:
            raise DocumentError(str(error))

        payload = state.get("payload")
        if not isinstance(payload, (bytes, bytearray)):
            raise DocumentError("Server returned an invalid document payload.")
        return bytes(payload)

    def handle_response(self, msg: dict) -> None:
        if msg.get("ok"):
            return
        self._resolve_request(
            msg.get("document_id"),
            error=msg.get("error") or "Server could not provide the requested document.",
        )

    def handle_resource(self, resource) -> None:
        manager = self._manager
        metadata = getattr(resource, "metadata", None)
        if not isinstance(metadata, dict):
            self._log.warning("Document resource missing metadata")
            return

        record = metadata.get("record")
        if not isinstance(record, dict):
            self._log.warning("Document resource missing record metadata")
            return

        try:
            doc_id = int(record.get("id"))
        except (TypeError, ValueError):
            self._log.warning("Document resource missing valid id: %r", record.get("id"))
            return

        with manager._document_request_lock:
            if doc_id not in manager._pending_document_requests:
                self._log.debug("Ignoring unsolicited document resource id=%s", doc_id)
                return

        if resource.status != RNS.Resource.COMPLETE:
            self._resolve_request(
                doc_id,
                error=f"Document transfer failed (status={resource.status}).",
            )
            return

        try:
            plaintext = resource.data.read()
        except Exception as exc:
            self._resolve_request(
                doc_id,
                error=f"Could not read document transfer: {exc}",
            )
            return

        from talon_core.config import get_document_storage_path
        from talon_core.documents import cache_document_download

        storage_root = get_document_storage_path(manager._cfg)
        try:
            manager._apply_record("documents", record, badge=False)
            with manager._lock:
                cache_document_download(
                    manager._conn,
                    manager._db_key,
                    storage_root,
                    doc_id,
                    plaintext,
                )
        except Exception as exc:
            self._resolve_request(
                doc_id,
                error=f"Could not cache downloaded document: {exc}",
            )
            return

        self._log.info("Document received from server: id=%s bytes=%d", doc_id, len(plaintext))
        self._resolve_request(doc_id, payload=bytes(plaintext))

    def invalidate_for_record(self, record: dict) -> None:
        manager = self._manager
        record_id = record.get("id")
        incoming_hash = record.get("sha256_hash")
        if record_id is None or not isinstance(incoming_hash, str):
            return

        from talon_core.config import get_document_storage_path
        from talon_core.documents import evict_document_cache

        try:
            doc_id = int(record_id)
        except (TypeError, ValueError):
            return

        row = manager._conn.execute(
            "SELECT file_path, sha256_hash FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            return
        cached_path, cached_hash = row
        if not cached_path or cached_hash == incoming_hash:
            return

        storage_root = get_document_storage_path(manager._cfg)
        evict_document_cache(
            manager._conn,
            storage_root,
            doc_id,
            clear_db_path=True,
            commit=False,
        )

    def remove_for_delete(self, document_id: typing.Any) -> None:
        manager = self._manager
        try:
            doc_id = int(document_id)
        except (TypeError, ValueError):
            return

        from talon_core.config import get_document_storage_path
        from talon_core.documents import evict_document_cache

        storage_root = get_document_storage_path(manager._cfg)
        evict_document_cache(
            manager._conn,
            storage_root,
            doc_id,
            clear_db_path=False,
            commit=False,
        )

    def fail_all_pending(self, message: str) -> None:
        manager = self._manager
        with manager._document_request_lock:
            pending = list(manager._pending_document_requests.values())
            manager._pending_document_requests.clear()
        for state in pending:
            state["error"] = message
            state["event"].set()

    def _resolve_request(
        self,
        document_id: typing.Any,
        *,
        payload: typing.Optional[bytes] = None,
        error: typing.Optional[str] = None,
    ) -> None:
        try:
            doc_id = int(document_id)
        except (TypeError, ValueError):
            return

        with self._manager._document_request_lock:
            state = self._manager._pending_document_requests.pop(doc_id, None)
        if state is None:
            return

        if error is not None:
            state["error"] = error
        else:
            state["payload"] = payload
            state["error"] = None
        state["event"].set()


class ClientRecordApplier:
    """Apply server-sourced records and deletes to the local store."""

    def __init__(
        self,
        manager,
        *,
        ui_dispatcher: ClientUiDispatcher,
        logger,
    ) -> None:
        self._manager = manager
        self._ui_dispatcher = ui_dispatcher
        self._log = logger

    def handle_chunk_data(self, msg: dict) -> typing.Optional[bytes]:
        return self._manager._chunk_reassembler.handle(msg)

    def gc_chunk_buffers(self) -> None:
        self._manager._chunk_reassembler.gc()

    def update_lease_expiry(self, lease_expires_at: typing.Any) -> None:
        manager = self._manager
        if not lease_expires_at or not manager._operator_id:
            return
        with manager._lock:
            try:
                manager._conn.execute(
                    "UPDATE operators SET lease_expires_at = ? WHERE id = ?",
                    (int(lease_expires_at), manager._operator_id),
                )
                manager._conn.commit()
            except Exception as exc:
                self._log.warning("Could not update lease in local DB: %s", exc)

    def mark_operator_revoked(
        self,
        operator_id: typing.Optional[typing.Any] = None,
        lease_expires_at: typing.Optional[typing.Any] = None,
        version: typing.Optional[typing.Any] = None,
    ) -> None:
        manager = self._manager
        try:
            op_id = int(
                operator_id if operator_id is not None else manager._operator_id
            )
        except (TypeError, ValueError):
            return
        if op_id <= 0:
            return

        now = int(time.time())
        try:
            expires_at = int(lease_expires_at) if lease_expires_at is not None else now
        except (TypeError, ValueError):
            expires_at = now
        try:
            server_version = int(version) if version is not None else None
        except (TypeError, ValueError):
            server_version = None

        was_revoked = False
        changed = False
        with manager._lock:
            try:
                row = manager._conn.execute(
                    "SELECT revoked FROM operators WHERE id = ?",
                    (op_id,),
                ).fetchone()
                was_revoked = bool(row[0]) if row is not None else False
                if row is None:
                    if op_id != manager._operator_id:
                        return
                    manager._conn.execute(
                        "INSERT INTO operators "
                        "(id, callsign, rns_hash, skills, profile, enrolled_at, "
                        "lease_expires_at, revoked, version) "
                        "VALUES (?, ?, '', '[]', '{}', ?, ?, 1, ?)",
                        (op_id, "REVOKED", now, expires_at, server_version or 1),
                    )
                elif server_version is not None:
                    manager._conn.execute(
                        "UPDATE operators SET revoked = 1, rns_hash = '', "
                        "lease_expires_at = ?, "
                        "version = CASE WHEN version < ? THEN ? ELSE version END "
                        "WHERE id = ?",
                        (expires_at, server_version, server_version, op_id),
                    )
                else:
                    manager._conn.execute(
                        "UPDATE operators SET revoked = 1, rns_hash = '', "
                        "lease_expires_at = ?, "
                        "version = version + CASE WHEN revoked = 0 THEN 1 ELSE 0 END "
                        "WHERE id = ?",
                        (expires_at, op_id),
                    )
                manager._conn.commit()
                changed = True
            except Exception as exc:
                self._log.warning(
                    "Could not mark operator revoked locally id=%s: %s",
                    op_id,
                    exc,
                )

        if not changed:
            return

        self._ui_dispatcher.notify("operators")
        if op_id == manager._operator_id and not was_revoked:
            self._log.warning("Local operator revoked by server: id=%s", op_id)
            manager._trigger_local_lock_check()

    def apply_record(self, table: str, record: dict, *, badge: bool = True) -> bool:
        manager = self._manager
        if not is_syncable(table):
            self._log.warning(
                "Received record for non-allowlisted table %r - ignored",
                table,
            )
            return False

        record = prepare_server_record_for_client_store(
            table,
            record,
            manager._db_key,
            logger=self._log,
        )
        if record is None:
            return False

        applied = False
        local_operator_was_revoked = False
        with manager._lock:
            try:
                row = manager._conn.execute(
                    f"SELECT version FROM {_validated_table(table)} WHERE id = ?",
                    (record.get("id"),),
                ).fetchone()
                local_version = row[0] if row else None
            except Exception:
                local_version = None

            if table == "operators" and record.get("id") == manager._operator_id:
                try:
                    row = manager._conn.execute(
                        "SELECT revoked FROM operators WHERE id = ?",
                        (manager._operator_id,),
                    ).fetchone()
                    local_operator_was_revoked = bool(row[0]) if row else False
                except Exception:
                    local_operator_was_revoked = False

            try:
                if table == "documents":
                    manager._document_transfers.invalidate_for_record(record)
                SyncEngine.apply_server_record(
                    manager._conn,
                    table,
                    record,
                    local_version,
                )
                applied = True
            except Exception as exc:
                self._log.warning(
                    "Failed to apply record table=%s id=%s: %s",
                    table,
                    record.get("id"),
                    exc,
                )

        if applied:
            self._ui_dispatcher.notify(table, badge=badge)
            if (
                table == "operators"
                and record.get("id") == manager._operator_id
                and bool(record.get("revoked"))
                and not local_operator_was_revoked
            ):
                self._log.warning(
                    "Local operator row is revoked by server: id=%s",
                    manager._operator_id,
                )
                manager._trigger_local_lock_check()

        return applied

    def apply_delete(
        self,
        table: str,
        record_id: typing.Any,
        *,
        badge: bool = True,
    ) -> None:
        manager = self._manager
        if not table or record_id is None or not is_syncable(table):
            return
        try:
            rid = int(record_id)
        except (ValueError, TypeError):
            self._log.warning("Invalid record_id in delete: %r", record_id)
            return

        deleted = False
        with manager._lock:
            try:
                if table == "documents":
                    manager._document_transfers.remove_for_delete(rid)
                for sql in predelete_sql(table):
                    try:
                        manager._conn.execute(sql, (rid,))
                    except Exception as exc:
                        self._log.warning("FK preclear failed (%s): %s", sql, exc)
                manager._conn.execute(
                    f"DELETE FROM {_validated_table(table)} WHERE id = ?",
                    (rid,),
                )
                manager._conn.commit()
                deleted = True
            except Exception as exc:
                self._log.warning(
                    "Failed to apply delete table=%s id=%s: %s",
                    table,
                    rid,
                    exc,
                )

        if deleted:
            self._ui_dispatcher.notify(table, badge=badge)


class ClientTombstoneReconciler:
    """Apply tombstones and reconcile local rows against server snapshots."""

    def __init__(self, manager, *, logger) -> None:
        self._manager = manager
        self._log = logger

    def apply_tombstones(
        self,
        tombstones: list[dict],
        *,
        badge: bool = True,
    ) -> None:
        sorted_ts = sorted(
            tombstones,
            key=lambda item: TOMBSTONE_ORDER_MAP.get(item.get("table", ""), 999),
        )
        for tombstone in sorted_ts:
            self._manager._apply_delete(
                tombstone.get("table", ""),
                tombstone.get("record_id"),
                badge=badge,
            )

    def reconcile_with_server(
        self,
        server_id_sets: dict[str, list[int]],
        *,
        badge: bool = True,
    ) -> None:
        manager = self._manager
        if not server_id_sets:
            return

        orphans: list[tuple[str, int]] = []
        for table in TOMBSTONE_APPLY_ORDER:
            server_ids = server_id_sets.get(table)
            if server_ids is None or not is_syncable(table):
                continue
            server_id_set = set(server_ids)
            with manager._lock:
                try:
                    if is_offline_creatable(table):
                        rows = manager._conn.execute(
                            f"SELECT id FROM {_validated_table(table)} "
                            "WHERE sync_status != 'pending'"
                        ).fetchall()
                    else:
                        rows = manager._conn.execute(
                            f"SELECT id FROM {_validated_table(table)}"
                        ).fetchall()
                    for (record_id,) in rows:
                        if record_id not in server_id_set:
                            orphans.append((table, record_id))
                except Exception as exc:
                    self._log.warning(
                        "reconcile query failed table=%s: %s",
                        table,
                        exc,
                    )

        for table, record_id in orphans:
            self._log.info(
                "Reconcile: deleting orphan table=%s id=%s",
                table,
                record_id,
            )
            manager._apply_delete(table, record_id, badge=badge)


class ClientOutbox:
    """Handle pending client-authored records and push acknowledgements."""

    def __init__(
        self,
        manager,
        *,
        ui_dispatcher: ClientUiDispatcher,
        smart_send: typing.Callable[[RNS.Link, bytes], None],
        logger,
    ) -> None:
        self._manager = manager
        self._ui_dispatcher = ui_dispatcher
        self._smart_send = smart_send
        self._log = logger

    def collect_outbox(self) -> dict[str, list[dict]]:
        manager = self._manager
        outbox: dict[str, list[dict]] = {}
        with manager._lock:
            for table in OFFLINE_TABLES:
                try:
                    cursor = manager._conn.execute(
                        f"SELECT * FROM {_validated_table(table)} "
                        "WHERE sync_status = 'pending'"
                    )
                    cols = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    if not rows:
                        continue
                    records = []
                    for row in rows:
                        record = dict(zip(cols, row))
                        records.append(
                            prepare_client_outbox_record(
                                table,
                                record,
                                manager._db_key,
                                logger=self._log,
                            )
                        )
                    if records:
                        outbox[table] = records
                except Exception as exc:
                    self._log.warning(
                        "_collect_outbox failed table=%s: %s",
                        table,
                        exc,
                    )
        return outbox

    def apply_push_ack(self, accepted: list, rejected: list) -> None:
        manager = self._manager
        now = int(time.time())

        if accepted:
            with manager._lock:
                for table in OFFLINE_TABLES:
                    try:
                        placeholders = ",".join("?" * len(accepted))
                        manager._conn.execute(
                            f"DELETE FROM {_validated_table(table)} "
                            f"WHERE uuid IN ({placeholders}) "
                            "AND sync_status = 'pending'",
                            accepted,
                        )
                        manager._conn.commit()
                    except Exception as exc:
                        self._log.warning(
                            "push_ack: delete pending failed table=%s: %s",
                            table,
                            exc,
                        )
            self._log.info(
                "push_ack: %d record(s) accepted and pending rows cleared",
                len(accepted),
            )

        for item in rejected:
            uuid_val = item.get("uuid")
            if not uuid_val:
                continue
            with manager._lock:
                try:
                    manager._conn.execute(
                        "INSERT INTO amendments "
                        "(table_name, record_uuid, client_data, server_data, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            item.get("table", ""),
                            uuid_val,
                            json.dumps(item.get("client_record")),
                            json.dumps(item.get("server_record")),
                            now,
                        ),
                    )
                    manager._conn.commit()
                except Exception as exc:
                    self._log.warning(
                        "push_ack: amendments insert failed uuid=%s: %s",
                        uuid_val,
                        exc,
                    )
            self._ui_dispatcher.notify("amendments")

        if rejected:
            self._log.info(
                "push_ack: %d record(s) rejected - stored in amendments",
                len(rejected),
            )

    def push_pending_to_server(self, table: str, record_id: int) -> None:
        threading.Thread(
            target=self.push_record_pending,
            args=(table, record_id),
            daemon=True,
            name="talon-outbox-push",
        ).start()

    def push_record_pending(self, table: str, record_id: int) -> None:
        manager = self._manager
        if not is_offline_creatable(table):
            return

        with manager._lock:
            try:
                manager._conn.execute(
                    f"UPDATE {_validated_table(table)} "
                    "SET sync_status = 'pending' WHERE id = ?",
                    (record_id,),
                )
                manager._conn.commit()
            except Exception as exc:
                self._log.warning(
                    "mark pending failed table=%s id=%s: %s",
                    table,
                    record_id,
                    exc,
                )
                return

        link = manager._link
        if link is None or not manager._initial_sync_done:
            self._log.debug(
                "Not connected - record table=%s id=%s queued as pending for reconnect",
                table,
                record_id,
            )
            return

        outbox = manager._collect_outbox()
        if not outbox:
            return

        my_rns_hash = manager._identity.hash.hex() if manager._identity else ""
        self._smart_send(
            link,
            proto.encode(
                {
                    "type": proto.MSG_CLIENT_PUSH_RECORDS,
                    "operator_rns_hash": my_rns_hash,
                    "records": outbox,
                }
            ),
        )
        self._log.info(
            "Mid-session push: table=%s id=%s (%d table(s) total)",
            table,
            record_id,
            len(outbox),
        )


class ClientEnrollment:
    """Load local identity, restore enrollment state, and perform enrollment."""

    def __init__(
        self,
        manager,
        *,
        link_timeout_s: int,
        parse_combined: typing.Callable[[str], tuple[str, str]],
        recall_dest: typing.Callable[[bytes], typing.Optional[RNS.Destination]],
        teardown: typing.Callable[[RNS.Link], None],
        logger,
    ) -> None:
        self._manager = manager
        self._link_timeout_s = link_timeout_s
        self._parse_combined = parse_combined
        self._recall_dest = recall_dest
        self._teardown = teardown
        self._log = logger

    def load_identity(self) -> None:
        manager = self._manager
        from talon_core.config import get_data_dir
        from talon_core.crypto.identity import load_or_create_identity

        data_dir = get_data_dir(manager._cfg)
        identity_path = data_dir / "client.identity"
        manager._identity = load_or_create_identity(identity_path)
        self._log.info("Client identity loaded: %s", manager._identity.hash.hex())

    def restore_meta(self) -> None:
        manager = self._manager
        with manager._lock:
            rows = manager._conn.execute(
                "SELECT key, value FROM meta "
                "WHERE key IN ('server_rns_hash', 'my_operator_id')"
            ).fetchall()
        meta = {row[0]: row[1] for row in rows}

        server_hash_hex = meta.get("server_rns_hash", "").strip()
        if server_hash_hex:
            try:
                manager._server_hash = bytes.fromhex(server_hash_hex)
            except ValueError:
                self._log.warning(
                    "Invalid server_rns_hash in meta: %r",
                    server_hash_hex,
                )

        operator_id_str = meta.get("my_operator_id", "").strip()
        if operator_id_str:
            try:
                manager._operator_id = int(operator_id_str)
            except ValueError:
                self._log.warning(
                    "Invalid my_operator_id in meta: %r",
                    operator_id_str,
                )

    def enroll(
        self,
        combined: str,
        callsign: str,
        on_success: typing.Callable[[int], None],
        on_error: typing.Callable[[str], None],
    ) -> None:
        threading.Thread(
            target=self.do_enroll,
            args=(combined, callsign, on_success, on_error),
            daemon=True,
            name="talon-enroll",
        ).start()

    def do_enroll(
        self,
        combined: str,
        callsign: str,
        on_success: typing.Callable[[int], None],
        on_error: typing.Callable[[str], None],
    ) -> None:
        manager = self._manager
        try:
            token, server_hash_hex = self._parse_combined(combined)
        except ValueError as exc:
            on_error(str(exc))
            return

        try:
            server_hash_bytes = bytes.fromhex(server_hash_hex)
        except ValueError:
            on_error(
                f"Invalid server hash in enrollment string: {server_hash_hex!r}"
            )
            return

        dest = self._recall_dest(server_hash_bytes)
        if dest is None:
            on_error(
                "Server not reachable - could not find server on the network.\n"
                "Check that the server is running and the RNS loopback interfaces are configured."
            )
            return

        result: dict[str, typing.Any] = {}
        event = threading.Event()
        my_rns_hash = manager._identity.hash.hex() if manager._identity else ""

        def _on_established(link: RNS.Link) -> None:
            pkt = proto.encode(
                {
                    "type": proto.MSG_ENROLL_REQUEST,
                    "token": token,
                    "callsign": callsign,
                    "rns_hash": my_rns_hash,
                }
            )
            try:
                RNS.Packet(link, pkt).send()
            except Exception as exc:
                result["error"] = f"Failed to send enroll request: {exc}"
                event.set()
                self._teardown(link)

        def _on_packet(data: bytes, _packet) -> None:
            try:
                result["msg"] = proto.decode(data)
            except ValueError as exc:
                result["error"] = f"Malformed response: {exc}"
                event.set()
                return
            try:
                proto.validate_server_message(result["msg"])
            except proto.ProtocolValidationError as exc:
                result["error"] = f"Malformed response: {exc}"
            event.set()

        def _on_closed(_link: RNS.Link) -> None:
            if not event.is_set():
                result.setdefault(
                    "error",
                    "Link closed before response was received",
                )
                event.set()

        link = RNS.Link(dest)
        link.set_link_established_callback(_on_established)
        link.set_packet_callback(_on_packet)
        link.set_link_closed_callback(_on_closed)

        if not event.wait(timeout=self._link_timeout_s):
            result["error"] = "Enrollment timed out - server did not respond"
            self._teardown(link)

        if "error" in result:
            on_error(result["error"])
            return

        msg = result.get("msg") or {}
        msg_type = msg.get("type")

        if msg_type == proto.MSG_ENROLL_RESPONSE:
            if msg.get("ok"):
                operator_id = int(msg["operator_id"])
                with manager._lock:
                    manager._conn.execute(
                        "INSERT OR REPLACE INTO meta (key, value) "
                        "VALUES ('server_rns_hash', ?)",
                        (server_hash_hex,),
                    )
                    manager._conn.execute(
                        "INSERT OR REPLACE INTO meta (key, value) "
                        "VALUES ('my_operator_id', ?)",
                        (str(operator_id),),
                    )
                    manager._conn.commit()
                manager._server_hash = server_hash_bytes
                manager._operator_id = operator_id
                on_success(operator_id)
            else:
                on_error(msg.get("error") or "Enrollment denied by server")
        elif msg_type == proto.MSG_ERROR:
            on_error(msg.get("message") or "Server returned an error")
        else:
            on_error(f"Unexpected response type: {msg_type!r}")


class ClientLinkLifecycle:
    """Maintain broadband and LoRa sync sessions once the client is enrolled."""

    def __init__(
        self,
        manager,
        *,
        link_timeout_s: int,
        reconnect_base_s: int,
        reconnect_max_s: int,
        smart_send: typing.Callable[[RNS.Link, bytes], None],
        teardown: typing.Callable[[RNS.Link], None],
        logger,
    ) -> None:
        self._manager = manager
        self._link_timeout_s = link_timeout_s
        self._reconnect_base_s = reconnect_base_s
        self._reconnect_max_s = reconnect_max_s
        self._smart_send = smart_send
        self._teardown = teardown
        self._log = logger

    def connection_loop(self) -> None:
        manager = self._manager
        manager._reconnect_backoff = self._reconnect_base_s
        while not manager._stop_event.is_set():
            if not manager._server_hash:
                manager._stop_event.wait(timeout=10)
                continue

            dest = manager._recall_dest(manager._server_hash)
            if dest is None:
                self._log.warning("Server not reachable - retrying in 15 s")
                manager._stop_event.wait(timeout=15)
                continue

            try:
                self.run_session(dest)
                manager._reconnect_backoff = self._reconnect_base_s
            except Exception as exc:
                self._log.warning("Sync session error: %s", exc, exc_info=True)

            if not manager._stop_event.is_set():
                self._log.info(
                    "Reconnecting in %d s",
                    manager._reconnect_backoff,
                )
                manager._stop_event.wait(timeout=manager._reconnect_backoff)
                manager._reconnect_backoff = min(
                    manager._reconnect_backoff * 2,
                    self._reconnect_max_s,
                )

    def run_session(self, dest: RNS.Destination) -> None:
        manager = self._manager
        session_ended = threading.Event()
        sync_done_event = threading.Event()
        my_rns_hash = manager._identity.hash.hex() if manager._identity else ""

        def _send_sync_request(link: RNS.Link) -> None:
            with manager._lock:
                version_map = SyncEngine.build_version_map(manager._conn)

            wire_vm = {
                table: {
                    str(record_id): version
                    for record_id, version in versions.items()
                }
                for table, versions in version_map.items()
            }
            self._smart_send(
                link,
                proto.encode(
                    {
                        "type": proto.MSG_SYNC_REQUEST,
                        "operator_rns_hash": my_rns_hash,
                        "version_map": wire_vm,
                        "last_sync_at": manager._last_sync_at,
                    }
                ),
            )

        def _process_data(data: bytes) -> None:
            try:
                msg = proto.decode(data)
            except ValueError:
                return
            if msg.get("type") == proto.MSG_CHUNK:
                try:
                    proto.validate_server_message(msg)
                except proto.ProtocolValidationError as exc:
                    self._log.warning("Invalid server chunk: %s", exc)
                    return
                reassembled = manager._handle_chunk_data(msg)
                if reassembled is None:
                    return
                try:
                    msg = proto.decode(reassembled)
                except ValueError:
                    return
            manager._handle_incoming(msg, sync_done_event, _send_sync_request)

        def _process_resource(resource) -> None:
            metadata = getattr(resource, "metadata", None)
            if isinstance(metadata, dict) and metadata.get("type") == proto.MSG_DOCUMENT_RESPONSE:
                manager._handle_document_resource(resource)
                return
            if resource.status == RNS.Resource.COMPLETE:
                _process_data(resource.data.read())

        def _on_established(link: RNS.Link) -> None:
            manager._link = link
            outbox = manager._collect_outbox()
            if outbox:
                self._log.info(
                    "Persistent link established - pushing outbox (%d table(s)) then sync_request",
                    len(outbox),
                )
                self._smart_send(
                    link,
                    proto.encode(
                        {
                            "type": proto.MSG_CLIENT_PUSH_RECORDS,
                            "operator_rns_hash": my_rns_hash,
                            "records": outbox,
                        }
                    ),
                )
            else:
                self._log.info(
                    "Persistent link established - sending sync_request"
                )
                _send_sync_request(link)

        def _on_closed(_link: RNS.Link) -> None:
            manager._link = None
            manager._initial_sync_done = False
            manager._fail_pending_document_requests(
                "Document transfer interrupted because the sync link closed."
            )
            self._log.info("Persistent link closed")
            session_ended.set()
            sync_done_event.set()

        link = RNS.Link(dest)
        link.set_link_established_callback(_on_established)
        link.set_packet_callback(lambda data, _pkt: _process_data(data))
        link.set_resource_callback(lambda _resource: True)
        link.set_resource_concluded_callback(_process_resource)
        link.set_link_closed_callback(_on_closed)

        if not sync_done_event.wait(timeout=self._link_timeout_s):
            self._log.warning("Initial sync timed out - dropping link")
            self._teardown(link)
            return

        if session_ended.is_set():
            return

        self._log.info(
            "Initial sync complete - entering push-receive / heartbeat loop"
        )
        while True:
            wait_until = time.time() + HEARTBEAT_BROADBAND_S
            while time.time() < wait_until:
                if manager._stop_event.is_set() or session_ended.is_set():
                    break
                time.sleep(1)

            if manager._stop_event.is_set() or session_ended.is_set():
                break

            if manager._link:
                self._smart_send(
                    manager._link,
                    proto.encode(
                        {
                            "type": proto.MSG_HEARTBEAT,
                            "operator_rns_hash": my_rns_hash,
                        }
                    ),
                )
                self._log.debug("Heartbeat sent on persistent link")
            manager._gc_chunk_buffers()

        self._teardown(link)

    def lora_polling_loop(self) -> None:
        self.do_lora_cycle()
        while not self._manager._stop_event.wait(timeout=HEARTBEAT_LORA_S):
            self.do_lora_cycle()

    def do_lora_cycle(self) -> None:
        manager = self._manager
        if manager._conn is None or not manager._server_hash or manager._operator_id is None:
            return
        dest = manager._recall_dest(manager._server_hash)
        if dest is None:
            self._log.warning("Server not in announce table - skipping LoRa cycle")
            return
        my_rns_hash = manager._identity.hash.hex() if manager._identity else ""
        self.lora_push_outbox(dest, my_rns_hash)
        self.lora_sync(dest, my_rns_hash)
        self.lora_heartbeat(dest, my_rns_hash)
        manager._gc_chunk_buffers()

    def lora_push_outbox(self, dest: RNS.Destination, my_rns_hash: str) -> None:
        manager = self._manager
        outbox = manager._collect_outbox()
        if not outbox:
            return

        result: dict[str, typing.Any] = {"ack": None, "error": None}
        event = threading.Event()

        def _on_established(link: RNS.Link) -> None:
            self._smart_send(
                link,
                proto.encode(
                    {
                        "type": proto.MSG_CLIENT_PUSH_RECORDS,
                        "operator_rns_hash": my_rns_hash,
                        "records": outbox,
                    }
                ),
            )

        def _on_packet(data: bytes, _pkt) -> None:
            try:
                msg = proto.decode(data)
            except ValueError:
                event.set()
                return
            try:
                proto.validate_server_message(msg)
            except proto.ProtocolValidationError as exc:
                result["error"] = f"malformed response: {exc}"
                event.set()
                return
            if msg.get("type") == proto.MSG_PUSH_ACK:
                result["ack"] = msg
            elif msg.get("type") == proto.MSG_ERROR:
                result["error"] = msg.get("code") or msg.get("message", "unknown error")
            else:
                result["error"] = f"unexpected response: {msg.get('type')}"
            event.set()

        def _on_closed(_link: RNS.Link) -> None:
            if not event.is_set():
                event.set()

        link = RNS.Link(dest)
        link.set_link_established_callback(_on_established)
        link.set_packet_callback(_on_packet)
        link.set_link_closed_callback(_on_closed)

        if not event.wait(timeout=self._link_timeout_s):
            self._log.warning("LoRa outbox push timed out")
            self._teardown(link)
            return

        if result["error"]:
            self._log.warning("LoRa outbox push error: %s", result["error"])
            if result["error"] == proto.ERROR_OPERATOR_INACTIVE:
                manager._handle_operator_inactive()
        elif result["ack"]:
            ack = result["ack"]
            manager._apply_push_ack(
                ack.get("accepted") or [],
                ack.get("rejected") or [],
            )

        self._teardown(link)

    def lora_sync(self, dest: RNS.Destination, my_rns_hash: str) -> None:
        manager = self._manager
        with manager._lock:
            version_map = SyncEngine.build_version_map(manager._conn)

        wire_vm = {
            table: {str(record_id): version for record_id, version in versions.items()}
            for table, versions in version_map.items()
        }

        result: dict[str, typing.Any] = {
            "responses": [],
            "done": False,
            "tombstones": [],
            "server_id_sets": {},
            "error": None,
        }
        event = threading.Event()

        def _process(data: bytes) -> None:
            try:
                msg = proto.decode(data)
            except ValueError:
                return
            if msg.get("type") == proto.MSG_CHUNK:
                try:
                    proto.validate_server_message(msg)
                except proto.ProtocolValidationError as exc:
                    self._log.warning("Invalid server chunk: %s", exc)
                    return
                reassembled = manager._handle_chunk_data(msg)
                if reassembled is None:
                    return
                try:
                    msg = proto.decode(reassembled)
                except ValueError:
                    return
            try:
                proto.validate_server_message(msg)
            except proto.ProtocolValidationError as exc:
                result["error"] = f"malformed response: {exc}"
                event.set()
                return

            msg_type = msg.get("type")
            if msg_type == proto.MSG_SYNC_RESPONSE:
                result["responses"].append(msg)
            elif msg_type == proto.MSG_SYNC_DONE:
                result["done"] = True
                result["tombstones"] = msg.get("tombstones") or []
                result["server_id_sets"] = msg.get("server_id_sets") or {}
                event.set()
            elif msg_type == proto.MSG_ERROR:
                result["error"] = msg.get("code") or msg.get("message", "unknown error")
                event.set()

        def _on_established(link: RNS.Link) -> None:
            self._smart_send(
                link,
                proto.encode(
                    {
                        "type": proto.MSG_SYNC_REQUEST,
                        "operator_rns_hash": my_rns_hash,
                        "version_map": wire_vm,
                        "last_sync_at": manager._last_sync_at,
                    }
                ),
            )

        link = RNS.Link(dest)
        link.set_link_established_callback(_on_established)
        link.set_packet_callback(lambda data, _pkt: _process(data))
        link.set_resource_callback(lambda _resource: True)
        link.set_resource_concluded_callback(
            lambda resource: _process(resource.data.read())
            if resource.status == RNS.Resource.COMPLETE
            else None
        )
        link.set_link_closed_callback(
            lambda _link: event.set() if not event.is_set() else None
        )

        if not event.wait(timeout=self._link_timeout_s):
            self._log.warning("LoRa sync timed out")
            self._teardown(link)
            return

        if result["error"]:
            self._log.warning("LoRa sync error: %s", result["error"])
            if result["error"] == proto.ERROR_OPERATOR_INACTIVE:
                manager._handle_operator_inactive()
            self._teardown(link)
            return

        notify_badge = not manager._suppress_startup_sync_badges
        applied = 0
        for response in result["responses"]:
            table = response.get("table", "")
            record = response.get("record")
            if record and table:
                manager._apply_record(table, record, badge=notify_badge)
                applied += 1

        if result["done"]:
            manager._apply_tombstones(result["tombstones"], badge=notify_badge)
            manager._reconcile_with_server(
                result["server_id_sets"],
                badge=notify_badge,
            )
            manager._last_sync_at = int(time.time())
            manager._initial_sync_done = True
            manager._suppress_startup_sync_badges = False

        if applied:
            self._log.info("LoRa sync applied %d record(s)", applied)
        self._teardown(link)

    def lora_heartbeat(self, dest: RNS.Destination, my_rns_hash: str) -> None:
        manager = self._manager
        result: dict[str, typing.Any] = {"msg": None, "error": None}
        event = threading.Event()

        def _on_established(link: RNS.Link) -> None:
            self._smart_send(
                link,
                proto.encode(
                    {
                        "type": proto.MSG_HEARTBEAT,
                        "operator_rns_hash": my_rns_hash,
                    }
                ),
            )

        def _on_packet(data: bytes, _pkt) -> None:
            try:
                result["msg"] = proto.decode(data)
            except ValueError as exc:
                result["error"] = f"Malformed heartbeat response: {exc}"
                event.set()
                return
            try:
                proto.validate_server_message(result["msg"])
            except proto.ProtocolValidationError as exc:
                result["error"] = f"Malformed heartbeat response: {exc}"
            event.set()

        def _on_closed(_link: RNS.Link) -> None:
            if not event.is_set():
                event.set()

        link = RNS.Link(dest)
        link.set_link_established_callback(_on_established)
        link.set_packet_callback(_on_packet)
        link.set_link_closed_callback(_on_closed)

        if not event.wait(timeout=self._link_timeout_s):
            self._log.warning("LoRa heartbeat timed out")
            self._teardown(link)
            return

        if result["error"]:
            self._log.warning("LoRa heartbeat error: %s", result["error"])
            self._teardown(link)
            return

        msg = result.get("msg") or {}
        if msg.get("type") == proto.MSG_HEARTBEAT_ACK:
            manager._update_lease_expiry(msg.get("lease_expires_at"))
        elif msg.get("type") == proto.MSG_ERROR:
            self._log.warning("LoRa heartbeat error: %s", msg.get("message"))
            if msg.get("code") == proto.ERROR_OPERATOR_INACTIVE:
                manager._handle_operator_inactive()
        self._teardown(link)

    def handle_incoming(
        self,
        msg: dict,
        sync_done_event: threading.Event,
        send_sync_request: typing.Optional[typing.Callable[[RNS.Link], None]] = None,
    ) -> None:
        manager = self._manager
        try:
            proto.validate_server_message(msg)
        except proto.ProtocolValidationError as exc:
            self._log.warning("Invalid server message: %s", exc)
            return

        msg_type = msg.get("type")
        if msg_type == proto.MSG_SYNC_RESPONSE:
            table = msg.get("table", "")
            record = msg.get("record")
            if record and table:
                manager._apply_record(
                    table,
                    record,
                    badge=not manager._suppress_startup_sync_badges,
                )

        elif msg_type == proto.MSG_SYNC_DONE:
            tombstones = msg.get("tombstones") or []
            notify_badge = not manager._suppress_startup_sync_badges
            manager._apply_tombstones(tombstones, badge=notify_badge)
            manager._reconcile_with_server(
                msg.get("server_id_sets") or {},
                badge=notify_badge,
            )
            manager._last_sync_at = int(time.time())
            manager._initial_sync_done = True
            manager._suppress_startup_sync_badges = False
            self._log.debug(
                "Sync done (tombstones=%d, last_sync_at=%d)",
                len(tombstones),
                manager._last_sync_at,
            )
            sync_done_event.set()

        elif msg_type == proto.MSG_PUSH_UPDATE:
            table = msg.get("table", "")
            record = msg.get("record")
            if record and table:
                applied = manager._apply_record(table, record)
                if applied:
                    self._log.debug(
                        "Push update applied: table=%s id=%s",
                        table,
                        record.get("id"),
                    )
                elif send_sync_request is not None and manager._link is not None:
                    self._log.info(
                        "Push update deferred; requesting dependency sync: table=%s id=%s",
                        table,
                        record.get("id"),
                    )
                    send_sync_request(manager._link)

        elif msg_type == proto.MSG_PUSH_DELETE:
            table = msg.get("table", "")
            record_id = msg.get("record_id")
            if table and record_id is not None:
                manager._apply_delete(table, record_id)
                self._log.debug(
                    "Push delete applied: table=%s id=%s",
                    table,
                    record_id,
                )

        elif msg_type == proto.MSG_HEARTBEAT_ACK:
            manager._update_lease_expiry(msg.get("lease_expires_at"))

        elif msg_type == proto.MSG_DOCUMENT_RESPONSE:
            manager._handle_document_response(msg)

        elif msg_type == proto.MSG_OPERATOR_REVOKED:
            manager._mark_operator_revoked(
                msg.get("operator_id"),
                msg.get("lease_expires_at"),
                msg.get("version"),
            )
            if (
                manager._link is not None
                and msg.get("operator_id") == manager._operator_id
            ):
                self._teardown(manager._link)

        elif msg_type == proto.MSG_PUSH_ACK:
            manager._apply_push_ack(
                msg.get("accepted") or [],
                msg.get("rejected") or [],
            )
            if (
                not manager._initial_sync_done
                and send_sync_request is not None
                and manager._link is not None
            ):
                send_sync_request(manager._link)

        elif msg_type == proto.MSG_ERROR:
            self._log.warning("Error from server: %s", msg.get("message"))
            if msg.get("code") == proto.ERROR_OPERATOR_INACTIVE:
                manager._handle_operator_inactive()
                if manager._link is not None:
                    self._teardown(manager._link)
