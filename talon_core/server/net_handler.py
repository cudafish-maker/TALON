"""
Server network handler — incoming link acceptance and message routing.

Creates the server's ``talon.server`` RNS destination, announces it, and
dispatches incoming client messages:

  enroll_request  → validate one-time token, create operator, reply enroll_response
                    (link torn down after; new operator pushed to connected clients)
  sync_request    → build per-table delta + tombstones; reply N×sync_response +
                    sync_done; KEEP LINK OPEN for push notifications
  heartbeat       → verify operator, renew lease if needed, reply heartbeat_ack
                    (link stays open)
  push_update     → (outbound) server pushes one record to all connected clients
                    after any DB write
  push_delete     → (outbound) server pushes a delete + tombstone to all connected
                    clients after any DB delete

For broadband (Yggdrasil/I2P/TCP) each client maintains one persistent link that
is used for both the initial delta sync and all subsequent push notifications.
LoRa clients use the same protocol but call sync_request + heartbeat on separate
short-lived links (new-link-per-cycle behaviour is preserved by the client side).

Payload size: ``talon.network.framing.smart_send`` uses ``RNS.Packet`` for
messages <= 380 bytes and manual MSG_CHUNK framing for larger payloads,
preventing silent packet drops on any transport's MTU limit.
"""
import threading
import typing
import uuid as _uuid_mod

import RNS

from talon_core.constants import RNS_APP_NAME, RNS_SERVER_ASPECT
from talon_core.server.net_components import (
    ServerActiveClients,
    ServerLinkRouter,
    ServerMessageHandlers,
    ServerPushDispatcher,
    ServerRecordSerializer,
    ServerSyncRepository,
    ServerUiDispatcher,
)
from talon_core.network.framing import (
    CHUNK_MAX_BUFFERS as _CHUNK_MAX_BUFFERS,
    CHUNK_MAX_TOTAL as _CHUNK_MAX_TOTAL,
    CHUNK_SIZE as _CHUNK_SIZE,
    PACKET_MAX as _PACKET_MAX,
    ChunkReassembler,
    smart_send,
)
from talon_core.network import protocol as proto
from talon_core.network.registry import serialise_record_for_wire
from talon_core.utils.logging import get_logger

_log = get_logger("server.net_handler")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _smart_send(link: RNS.Link, data: bytes) -> None:
    """Compatibility wrapper around the shared framing sender."""
    smart_send(link, data, logger=_log)


def _send_error(
    link: RNS.Link,
    message: str,
    *,
    code: typing.Optional[str] = None,
) -> None:
    try:
        payload = {"type": proto.MSG_ERROR, "message": message}
        if code is not None:
            payload["code"] = code
        RNS.Packet(link, proto.encode(payload)).send()
    except Exception as exc:
        _log.warning("_send_error failed: %s", exc)


def _teardown(link: RNS.Link) -> None:
    try:
        link.teardown()
    except Exception:
        pass


def _notify_ui(table: str) -> None:
    """Default no-op UI callback used outside a server adapter."""
    _ = table


def _is_hex(value: str) -> bool:
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _normalise_uuid(value: typing.Any) -> typing.Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return _uuid_mod.UUID(value).hex
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Handler class
# ---------------------------------------------------------------------------

class ServerNetHandler:
    """
    Manages the server's RNS sync destination lifecycle and all client
    push notifications.

    Thread-safety:
      ``_lock``       — serialises all DB access.
      ``_links_lock`` — serialises reads/writes to ``_active_links``.
      Both locks are never held simultaneously to prevent deadlock.
    """

    def __init__(
        self,
        conn,
        cfg,
        db_key: bytes,
        *,
        notify_ui: typing.Optional[typing.Callable[[str], None]] = None,
    ) -> None:
        self._conn = conn
        self._cfg = cfg
        self._db_key = db_key
        self._notify_ui = notify_ui or _notify_ui
        self._destination: typing.Optional[RNS.Destination] = None
        self._lock = threading.Lock()
        # operator_rns_hash → persistent RNS.Link (broadband clients)
        self._active_links: dict[str, RNS.Link] = {}
        self._links_lock = threading.Lock()
        self._chunk_reassembler = ChunkReassembler(logger=_log)
        # Compatibility aliases for existing tests and diagnostic inspection.
        self._chunk_buffers = self._chunk_reassembler.buffers
        self._chunk_lock = self._chunk_reassembler.lock
        # Push coalescing: enqueue changes then flush in a single 50ms burst
        self._push_buffer: dict[str, set] = {}   # table → set of record ids
        self._push_buffer_lock = threading.Lock()
        self._push_flush_scheduled: bool = False
        self._ui_dispatcher = ServerUiDispatcher(notify_ui=self._notify_ui)
        self._active_clients_component = ServerActiveClients(self)
        self._record_serializer = ServerRecordSerializer(
            self,
            serialise_record=_serialise_bytes,
        )
        self._sync_repository = ServerSyncRepository(
            self,
            serializer=self._record_serializer,
            logger=_log,
        )
        self._link_router = ServerLinkRouter(self, logger=_log)
        self._push_dispatcher = ServerPushDispatcher(
            self,
            active_clients=self._active_clients_component,
            smart_send=_smart_send,
            logger=_log,
        )
        self._message_handlers = ServerMessageHandlers(
            self,
            active_clients=self._active_clients_component,
            ui_dispatcher=self._ui_dispatcher,
            smart_send=_smart_send,
            is_hex=_is_hex,
            normalise_uuid=_normalise_uuid,
            logger=_log,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Create and announce the server destination. Must be called after the DB is open."""
        from talon_core.config import get_data_dir
        from talon_core.crypto.identity import load_or_create_identity

        data_dir = get_data_dir(self._cfg)
        identity_path = data_dir / "server.identity"
        identity = load_or_create_identity(identity_path)

        dest = RNS.Destination(
            identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            RNS_APP_NAME,
            RNS_SERVER_ASPECT,
        )
        dest.set_link_established_callback(self._on_link_established)
        dest.announce()
        self._destination = dest

        dest_hash_hex = dest.hash.hex()
        _log.info("Server sync destination announced: %s", dest_hash_hex)

        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('server_rns_hash', ?)",
                    (dest_hash_hex,),
                )
                self._conn.commit()
        except Exception as exc:
            _log.warning("Could not persist server_rns_hash in meta: %s", exc)

    def stop(self) -> None:
        """Tear down all active links and deregister the destination."""
        self._active_clients_component.close_all()
        self._destination = None
        _log.info("ServerNetHandler stopped")

    def status(self) -> dict[str, typing.Any]:
        """Return a UI-safe server sync status snapshot."""
        with self._links_lock:
            active_hashes = tuple(sorted(self._active_links))
        return {
            "started": self._destination is not None,
            "active_client_count": len(active_hashes),
            "active_client_hashes": active_hashes,
        }

    # ------------------------------------------------------------------
    # Link callbacks (called from RNS thread)
    # ------------------------------------------------------------------

    def _on_link_established(self, link: RNS.Link) -> None:
        self._link_router.on_link_established(link)

    def _on_resource(self, link: RNS.Link, resource) -> None:
        self._link_router.on_resource(link, resource)

    def _on_link_closed(self, link: RNS.Link) -> None:
        self._link_router.on_link_closed(link)

    def _on_packet(self, link: RNS.Link, data: bytes, _packet) -> None:
        self._link_router.on_packet(link, data, _packet)

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def _handle_enroll(self, link: RNS.Link, msg: dict) -> None:
        self._message_handlers.handle_enroll(link, msg)

    def _handle_sync(self, link: RNS.Link, msg: dict) -> None:
        self._message_handlers.handle_sync(link, msg)

    def _handle_heartbeat(self, link: RNS.Link, msg: dict) -> None:
        self._message_handlers.handle_heartbeat(link, msg)

    def _handle_document_request(self, link: RNS.Link, msg: dict) -> None:
        self._message_handlers.handle_document_request(link, msg)

    def _handle_client_push(self, link: RNS.Link, msg: dict) -> None:
        self._message_handlers.handle_client_push(link, msg)

    def _gc_tombstones(self) -> None:
        self._sync_repository.gc_tombstones()

    def _gc_chunk_buffers(self) -> None:
        self._chunk_reassembler.gc()

    # ------------------------------------------------------------------
    # Push notification API — called by server screens after any DB write
    # ------------------------------------------------------------------

    def notify_change(self, table: str, record_id: int) -> None:
        self._push_dispatcher.notify_change(table, record_id)

    def flush_pending_changes(self) -> None:
        """Flush queued push_update records after local server commands commit."""
        self._push_dispatcher.flush_push_buffer()

    def _flush_push_buffer(self) -> None:
        self._push_dispatcher.flush_push_buffer()

    def notify_delete(self, table: str, record_id: int) -> None:
        self._push_dispatcher.notify_delete(table, record_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _handle_chunk_data(self, msg: dict) -> typing.Optional[bytes]:
        """Compatibility wrapper around the shared chunk reassembler."""
        return self._chunk_reassembler.handle(msg)

    def _send_error(
        self,
        link: RNS.Link,
        message: str,
        *,
        code: typing.Optional[str] = None,
    ) -> None:
        if code is None:
            _send_error(link, message)
        else:
            _send_error(link, message, code=code)

    def _teardown_link(self, link: RNS.Link) -> None:
        _teardown(link)

    def _operator_active(self, rns_hash: str) -> bool:
        return self._sync_repository.operator_active(rns_hash)

    def _build_delta(self, table: str, client_versions: dict) -> list:
        return self._sync_repository.build_delta(table, client_versions)

    def _fetch_record(self, table: str, record_id: int) -> typing.Optional[dict]:
        return self._sync_repository.fetch_record(table, record_id)

    def _get_server_id_sets(self) -> dict:
        return self._sync_repository.get_server_id_sets()

    def _get_tombstones(self, since: int) -> list:
        return self._sync_repository.get_tombstones(since)


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def _serialise_bytes(record: dict, table: str, db_key: bytes) -> dict:
    """
    Convert bytes values in *record* to JSON-safe strings.

    ``sitreps.body`` is decrypted with *db_key* and returned as a UTF-8 string
    so the client can re-encrypt it with its own key after receiving.

    All other bytes values are decoded as UTF-8 (lossy) — the only remaining
    BLOB in the synced schema is ``messages.body``, which is plain UTF-8.
    """
    return serialise_record_for_wire(table, record, db_key, logger=_log)
