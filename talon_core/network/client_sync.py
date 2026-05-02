"""
Client sync manager — enrollment and real-time delta sync over RNS.

Responsibilities
----------------
1. Load/create the client's RNS identity (``client.identity`` in data_dir).
2. Provide ``enroll()`` — one-shot enrollment using a TOKEN:SERVER_HASH string.
3. Run a background connection loop that:
   a. Opens a **persistent** RNS Link to the server.
   b. Pushes any locally-created offline records (outbox) BEFORE sync_request.
   c. Sends a ``sync_request`` and applies the initial delta records and any
      tombstones (deletes) the client missed while offline.
   d. Keeps the link open to receive real-time ``push_update`` and
      ``push_delete`` messages from the server as data changes.
   e. Sends a ``heartbeat`` on the same persistent link every
      HEARTBEAT_BROADBAND_S seconds to keep the lease alive.
   f. Reconnects automatically with exponential backoff (5 s → 5 min) if
      the link drops.

LoRa mode
---------
Set ``[network] lora_mode = true`` in talon.ini to fall back to the
original poll-based behaviour (new link per cycle, 120-second interval).
This avoids hammering a low-bandwidth LoRa interface with a persistent
connection.  The LoRa cycle also flushes the outbox before sync.

Payload size
------------
``talon.network.framing.smart_send`` uses ``RNS.Packet`` for payloads <= 380
bytes and manual chunking (MSG_CHUNK) for larger ones, preventing silent drops
at the transport MTU limit.

Offline intel
-------------
Records created while offline are stored locally with sync_status='pending'.
On reconnect they are pushed via MSG_CLIENT_PUSH_RECORDS before the normal
sync_request.  The server accepts unknown UUIDs as new records; known UUIDs
(edit conflicts) are rejected and stored in the amendments table for review.
"""
import threading
import time
import typing

import RNS

from talon_core.constants import RNS_APP_NAME, RNS_SERVER_ASPECT
from talon_core.network.client_components import (
    ClientDocumentTransfers,
    ClientEnrollment,
    ClientLinkLifecycle,
    ClientOutbox,
    ClientRecordApplier,
    ClientTombstoneReconciler,
    ClientUiDispatcher,
)
from talon_core.network.framing import (
    CHUNK_BUFFER_TTL_S as _CHUNK_BUFFER_TTL_S,
    CHUNK_MAX_BUFFERS as _CHUNK_MAX_BUFFERS,
    CHUNK_MAX_TOTAL as _CHUNK_MAX_TOTAL,
    CHUNK_SIZE as _CHUNK_SIZE,
    PACKET_MAX as _PACKET_MAX,
    ChunkReassembler,
    smart_send,
)
from talon_core.utils.logging import get_logger

_log = get_logger("network.client_sync")

_LINK_TIMEOUT_S      = 30    # max wait for server response before giving up
_RECONNECT_BASE_S    = 5     # initial reconnect delay (doubles each failure)
_RECONNECT_MAX_S     = 300   # cap on reconnect delay (5 minutes)


def _smart_send(link: RNS.Link, data: bytes) -> None:
    """Compatibility wrapper around the shared framing sender."""
    smart_send(link, data, logger=_log)


class ClientSyncManager:
    """
    Manages client-side RNS enrollment and real-time delta sync.

    Thread-safety: public methods may be called from the UI thread.  The
    connection loop runs in a daemon thread.  All DB operations are
    serialised with ``_lock``.
    """

    def __init__(
        self,
        conn,
        cfg,
        db_key: bytes,
        *,
        notify_ui: typing.Optional[typing.Callable[..., None]] = None,
        trigger_lock_check: typing.Optional[typing.Callable[[int], None]] = None,
    ) -> None:
        self._conn = conn
        self._cfg = cfg
        self._db_key = db_key
        self._notify_ui = notify_ui or _notify_ui
        self._trigger_lock_check = trigger_lock_check
        self._identity: typing.Optional[RNS.Identity] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: typing.Optional[threading.Thread] = None
        # Populated after enrollment or restored from DB meta at start.
        self._server_hash: typing.Optional[bytes] = None
        self._operator_id: typing.Optional[int] = None
        # Unix timestamp of the last completed sync (used for tombstone query).
        self._last_sync_at: int = 0
        # Handle to the current persistent link (None when disconnected).
        self._link: typing.Optional[RNS.Link] = None
        self._connection_session_id: int = 0
        self._chunk_reassembler = ChunkReassembler(logger=_log)
        # Compatibility aliases for existing tests and diagnostic inspection.
        self._chunk_buffers = self._chunk_reassembler.buffers
        self._chunk_lock = self._chunk_reassembler.lock
        # Exponential backoff state for reconnect loop.
        self._reconnect_backoff: int = _RECONNECT_BASE_S
        # True after the initial MSG_SYNC_DONE is received on a session.
        # Used to distinguish initial-connection outbox pushes (which must
        # trigger a follow-up sync_request) from mid-session record pushes
        # (which must NOT retrigger a full sync).
        self._initial_sync_done: bool = False
        # The first sync after login establishes the UI baseline from existing
        # server state.  It should refresh visible screens but not create
        # unread badges for records the operator may have seen last session.
        self._suppress_startup_sync_badges: bool = True
        self._document_request_lock = threading.Lock()
        self._pending_document_requests: dict[int, dict[str, typing.Any]] = {}
        self._ui_dispatcher = ClientUiDispatcher(notify_ui=self._notify_ui)
        self._record_applier = ClientRecordApplier(
            self,
            ui_dispatcher=self._ui_dispatcher,
            logger=_log,
        )
        self._document_transfers = ClientDocumentTransfers(
            self,
            smart_send=_smart_send,
            logger=_log,
        )
        self._tombstone_reconciler = ClientTombstoneReconciler(
            self,
            logger=_log,
        )
        self._outbox = ClientOutbox(
            self,
            ui_dispatcher=self._ui_dispatcher,
            smart_send=_smart_send,
            logger=_log,
        )
        self._enrollment = ClientEnrollment(
            self,
            link_timeout_s=_LINK_TIMEOUT_S,
            parse_combined=_parse_combined,
            recall_dest=_recall_dest,
            teardown=_teardown,
            logger=_log,
        )
        self._link_lifecycle = ClientLinkLifecycle(
            self,
            link_timeout_s=_LINK_TIMEOUT_S,
            reconnect_base_s=_RECONNECT_BASE_S,
            reconnect_max_s=_RECONNECT_MAX_S,
            smart_send=_smart_send,
            teardown=_teardown,
            logger=_log,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Load the client identity, restore enrollment state from DB meta, and
        start the connection loop.  Does nothing if not yet enrolled.
        """
        self._load_identity()
        self._restore_meta()

        if not self._server_hash:
            _log.info("ClientSyncManager: not enrolled — connection loop deferred")
            return

        self._start_loop()

    def start_after_enroll(self) -> None:
        """Start the connection loop immediately after a successful enrollment."""
        self._start_loop()

    def stop(self) -> None:
        """Stop the connection loop (blocks up to 3 s for the thread to exit)."""
        self._stop_event.set()
        if self._link:
            _teardown(self._link)
        if self._thread:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                _log.warning("Client sync thread did not exit within timeout")
        _log.info("ClientSyncManager stopped")

    def _start_loop(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        is_lora = self._cfg.getboolean("network", "lora_mode", fallback=False)
        target = self._lora_polling_loop if is_lora else self._connection_loop
        self._thread = threading.Thread(
            target=target,
            daemon=True,
            name="talon-client-sync",
        )
        self._thread.start()
        mode = "lora-poll" if is_lora else "broadband-push"
        _log.info("Client sync loop started (%s, operator_id=%s)", mode, self._operator_id)

    def is_connected(self) -> bool:
        """Return True if the persistent broadband link is currently established."""
        return self._link is not None

    def status(self) -> dict[str, typing.Any]:
        """Return a UI-safe client sync status snapshot."""
        return {
            "started": self._thread is not None and self._thread.is_alive(),
            "connected": self.is_connected(),
            "enrolled": self._server_hash is not None and self._operator_id is not None,
            "operator_id": self._operator_id,
            "server_hash": self._server_hash.hex() if self._server_hash else None,
            "last_sync_at": self._last_sync_at or None,
            "initial_sync_done": self._initial_sync_done,
            "connection_session_id": self._connection_session_id,
        }

    def _connection_loop(self) -> None:
        self._link_lifecycle.connection_loop()

    def _run_session(self, dest: RNS.Destination) -> None:
        self._link_lifecycle.run_session(dest)

    def _lora_polling_loop(self) -> None:
        self._link_lifecycle.lora_polling_loop()

    def _do_lora_cycle(self) -> None:
        self._link_lifecycle.do_lora_cycle()

    def _lora_push_outbox(self, dest: RNS.Destination, my_rns_hash: str) -> None:
        self._link_lifecycle.lora_push_outbox(dest, my_rns_hash)

    def _lora_sync(self, dest: RNS.Destination, my_rns_hash: str) -> None:
        self._link_lifecycle.lora_sync(dest, my_rns_hash)

    def _lora_heartbeat(self, dest: RNS.Destination, my_rns_hash: str) -> None:
        self._link_lifecycle.lora_heartbeat(dest, my_rns_hash)

    def _handle_incoming(
        self,
        msg: dict,
        sync_done_event: threading.Event,
        send_sync_request: typing.Optional[typing.Callable[[RNS.Link], None]] = None,
    ) -> None:
        self._link_lifecycle.handle_incoming(
            msg,
            sync_done_event,
            send_sync_request,
        )

    def enroll(
        self,
        combined: str,
        callsign: str,
        on_success: typing.Callable[[int], None],
        on_error: typing.Callable[[str], None],
    ) -> None:
        self._enrollment.enroll(combined, callsign, on_success, on_error)

    def _do_enroll(
        self,
        combined: str,
        callsign: str,
        on_success: typing.Callable[[int], None],
        on_error: typing.Callable[[str], None],
    ) -> None:
        self._enrollment.do_enroll(combined, callsign, on_success, on_error)

    def _collect_outbox(self) -> dict:
        return self._outbox.collect_outbox()

    def _apply_push_ack(self, accepted: list, rejected: list) -> None:
        self._outbox.apply_push_ack(accepted, rejected)

    def _gc_chunk_buffers(self) -> None:
        self._record_applier.gc_chunk_buffers()

    def push_pending_to_server(self, table: str, record_id: int) -> None:
        self._outbox.push_pending_to_server(table, record_id)

    def push_record_pending(self, table: str, record_id: int) -> None:
        self._outbox.push_record_pending(table, record_id)

    def _push_record_pending(self, table: str, record_id: int) -> None:
        self._outbox.push_record_pending(table, record_id)

    def fetch_document(
        self,
        document_id: int,
        *,
        timeout_s: float = 60.0,
    ) -> bytes:
        return self._document_transfers.fetch_document(
            document_id,
            timeout_s=timeout_s,
        )

    def _handle_chunk_data(self, msg: dict) -> typing.Optional[bytes]:
        return self._record_applier.handle_chunk_data(msg)

    def _apply_record(self, table: str, record: dict, *, badge: bool = True) -> bool:
        return self._record_applier.apply_record(table, record, badge=badge)

    def _update_lease_expiry(self, lease_expires_at: typing.Any) -> None:
        self._record_applier.update_lease_expiry(lease_expires_at)

    def _handle_document_response(self, msg: dict) -> None:
        self._document_transfers.handle_response(msg)

    def _handle_document_resource(self, resource) -> None:
        self._document_transfers.handle_resource(resource)

    def _accept_resource(self, resource) -> bool:
        return self._document_transfers.accept_resource(resource)

    def _fail_pending_document_requests(self, message: str) -> None:
        self._document_transfers.fail_all_pending(message)

    def _mark_operator_revoked(
        self,
        operator_id: typing.Optional[typing.Any] = None,
        lease_expires_at: typing.Optional[typing.Any] = None,
        version: typing.Optional[typing.Any] = None,
    ) -> None:
        self._record_applier.mark_operator_revoked(
            operator_id,
            lease_expires_at,
            version,
        )

    def _handle_operator_inactive(self) -> None:
        self._record_applier.mark_operator_revoked(self._operator_id)

    def _handle_lease_expired(
        self,
        lease_expires_at: typing.Optional[typing.Any] = None,
    ) -> None:
        self._record_applier.mark_operator_lease_expired(lease_expires_at)

    def _trigger_local_lock_check(self) -> None:
        """
        Ask the app's lease monitor to re-check the local operator immediately.

        The normal SyncEngine heartbeat still catches this within its interval;
        this hook avoids waiting up to 60 seconds after an explicit network
        revocation packet arrives.
        """
        operator_id = self._operator_id
        if operator_id is None:
            return
        if self._trigger_lock_check is None:
            return
        try:
            self._trigger_lock_check(operator_id)
        except Exception as exc:
            _log.warning("Could not trigger lease lock check: %s", exc)

    def _apply_tombstones(self, tombstones: list, *, badge: bool = True) -> None:
        self._tombstone_reconciler.apply_tombstones(tombstones, badge=badge)

    def _reconcile_with_server(
        self,
        server_id_sets: dict,
        *,
        badge: bool = True,
    ) -> None:
        self._tombstone_reconciler.reconcile_with_server(
            server_id_sets,
            badge=badge,
        )

    def _apply_delete(
        self,
        table: str,
        record_id: typing.Any,
        *,
        badge: bool = True,
    ) -> None:
        self._record_applier.apply_delete(table, record_id, badge=badge)

    def _load_identity(self) -> None:
        self._enrollment.load_identity()

    def _restore_meta(self) -> None:
        self._enrollment.restore_meta()

    def _recall_dest(
        self,
        server_hash_bytes: bytes,
        path_timeout: float = 15.0,
    ) -> typing.Optional[RNS.Destination]:
        return _recall_dest(server_hash_bytes, path_timeout=path_timeout)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _notify_ui(
    table: str,
    *,
    badge: bool = True,
    action: str = "changed",
    record_id: int | None = None,
) -> None:
    """Default no-op UI callback used outside a client adapter."""
    _ = (table, badge, action, record_id)


def _parse_combined(combined: str) -> tuple:
    """Split a ``TOKEN:SERVER_HASH`` string into ``(token, server_hash_hex)``."""
    combined = combined.strip()
    if ":" not in combined:
        raise ValueError("Invalid enrollment string — expected TOKEN:SERVER_HASH format")
    token, server_hash_hex = combined.split(":", 1)
    token = token.strip()
    server_hash_hex = server_hash_hex.strip()
    if not token:
        raise ValueError("Token part is empty in enrollment string")
    if not server_hash_hex:
        raise ValueError("Server hash part is empty in enrollment string")
    return token, server_hash_hex


def _recall_dest(
    server_hash_bytes: bytes,
    path_timeout: float = 15.0,
) -> "typing.Optional[RNS.Destination]":
    """
    Reconstruct the server's outgoing RNS.Destination from its hash.

    First tries an immediate recall.  If the announce table is empty
    (common when the client starts after the server's announce fired),
    sends a path request which prompts the server to re-announce, then
    polls until the identity arrives or *path_timeout* expires.
    """
    def _build(identity: "RNS.Identity") -> "RNS.Destination":
        return RNS.Destination(
            identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            RNS_APP_NAME,
            RNS_SERVER_ASPECT,
        )

    try:
        identity = RNS.Identity.recall(server_hash_bytes)
        if identity is not None:
            return _build(identity)

        _log.info("Server identity not cached — requesting path (timeout=%.0fs)", path_timeout)
        RNS.Transport.request_path(server_hash_bytes)

        deadline = time.time() + path_timeout
        while time.time() < deadline:
            time.sleep(1.0)
            identity = RNS.Identity.recall(server_hash_bytes)
            if identity is not None:
                _log.info("Server identity received after path request")
                return _build(identity)

        _log.warning("Server identity still not known after %.0fs", path_timeout)
        return None
    except Exception as exc:
        _log.warning("_recall_dest failed: %s", exc)
        return None


def _teardown(link: RNS.Link) -> None:
    try:
        link.teardown()
    except Exception:
        pass
