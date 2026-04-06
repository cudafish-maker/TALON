# talon/net/link_manager.py
# Reticulum link lifecycle management.
#
# This module bridges T.A.L.O.N.'s sync/heartbeat layer with the
# actual RNS network. It handles:
#
# SERVER SIDE (ServerLinkManager):
#   - Creates an IN destination and announces it
#   - Accepts incoming links from clients
#   - Routes received packets to the sync engine or heartbeat monitor
#   - Sends notifications/responses back over established links
#
# CLIENT SIDE (ClientLinkManager):
#   - Resolves the server's destination hash
#   - Establishes an encrypted OUT link to the server
#   - Provides send_and_receive() — the send_fn for SyncClient.full_sync()
#   - Handles link teardown and reconnection
#
# Both sides use msgpack for serialization over the link. JSON is
# human-readable but msgpack is ~30% smaller and faster to parse.
# Over LoRa every byte matters.

import json
import threading
import time

import RNS

from talon.net.reticulum import APP_NAME

# How long to wait for a response before timing out (seconds).
RESPONSE_TIMEOUT = 30

# How long to wait for a link to be established (seconds).
LINK_TIMEOUT = 15


class ServerLinkManager:
    """Manages incoming Reticulum links on the server.

    Creates an IN destination that clients connect to. When a client
    establishes a link and sends a packet, the packet is decoded and
    dispatched to the appropriate handler (sync or heartbeat).

    Attributes:
        identity: The server's RNS.Identity.
        destination: The server's RNS.Destination (IN).
        on_sync_message: Callback(client_hash, message_dict) -> response_dict.
        on_heartbeat: Callback(client_hash, payload_dict).
        on_client_connected: Callback(client_hash, link).
        on_client_disconnected: Callback(client_hash).
    """

    def __init__(self, identity):
        self.identity = identity
        self.destination = None
        self._links = {}  # {client_hash: RNS.Link}
        self.on_sync_message = None
        self.on_heartbeat = None
        self.on_enrollment = None
        self.on_client_connected = None
        self.on_client_disconnected = None

    def start(self, aspect="sync"):
        """Create the server destination and start accepting links.

        Args:
            aspect: The destination aspect (default "sync").
        """
        self.destination = RNS.Destination(self.identity, RNS.Destination.IN, APP_NAME, aspect)
        self.destination.set_link_established_callback(self._link_established)
        self.destination.announce()

    def get_destination_hash(self) -> bytes:
        """Get this destination's hash for clients to connect to.

        Returns:
            The destination hash bytes.
        """
        if self.destination:
            return self.destination.hash
        return None

    def send_to_client(self, client_hash: str, data: dict) -> bool:
        """Send a message to a connected client.

        Args:
            client_hash: The client's identity hash (hex string).
            data: Dict to send (will be JSON-encoded).

        Returns:
            True if the packet was sent.
        """
        link = self._links.get(client_hash)
        if not link or link.status != RNS.Link.ACTIVE:
            return False

        payload = json.dumps(data).encode("utf-8")
        packet = RNS.Packet(link, payload)
        packet.send()
        return True

    def get_connected_clients(self) -> list:
        """Get hashes of all clients with active links."""
        return [h for h, link in self._links.items() if link.status == RNS.Link.ACTIVE]

    def stop(self):
        """Tear down all links and the destination."""
        for link in self._links.values():
            if link.status == RNS.Link.ACTIVE:
                link.teardown()
        self._links.clear()
        self.destination = None

    # --- Internal callbacks ---

    def _link_established(self, link):
        """Called by RNS when a client establishes a link."""
        client_hash = link.get_remote_identity().hexhash
        self._links[client_hash] = link

        link.set_packet_callback(lambda raw, _link=link, _hash=client_hash: self._packet_received(_hash, _link, raw))
        link.set_link_closed_callback(lambda _link, _hash=client_hash: self._link_closed(_hash))

        if self.on_client_connected:
            self.on_client_connected(client_hash, link)

    def _link_closed(self, client_hash):
        """Called when a client's link is torn down."""
        self._links.pop(client_hash, None)
        if self.on_client_disconnected:
            self.on_client_disconnected(client_hash)

    def _packet_received(self, client_hash, link, raw):
        """Called when a packet arrives from a client.

        Decodes the JSON payload, dispatches to the right handler,
        and sends the response back over the same link.
        """
        try:
            message = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        msg_type = message.get("type", "")

        if msg_type == "heartbeat":
            if self.on_heartbeat:
                self.on_heartbeat(client_hash, message)
            return

        if msg_type == "enrollment_request":
            if self.on_enrollment:
                response = self.on_enrollment(client_hash, message)
                if response:
                    payload = json.dumps(response).encode("utf-8")
                    packet = RNS.Packet(link, payload)
                    packet.send()
            return

        # Everything else goes to the sync handler
        if self.on_sync_message:
            response = self.on_sync_message(client_hash, message)
            if response:
                payload = json.dumps(response).encode("utf-8")
                packet = RNS.Packet(link, payload)
                packet.send()


class ClientLinkManager:
    """Manages the client's outgoing Reticulum link to the server.

    Establishes and maintains an encrypted link to the server's
    destination. Provides send_and_receive() which is used as the
    send_fn argument to SyncClient.full_sync().

    Attributes:
        identity: The client's RNS.Identity.
        server_dest_hash: The server destination hash to connect to.
        link: The active RNS.Link (or None).
        on_connected: Callback() when link is established.
        on_disconnected: Callback() when link is lost.
    """

    def __init__(self, identity, server_dest_hash: bytes):
        self.identity = identity
        self.server_dest_hash = server_dest_hash
        self.link = None
        self.on_connected = None
        self.on_disconnected = None
        self.on_push_message = None
        self._response = None
        self._response_event = threading.Event()

    def connect(self, timeout: float = LINK_TIMEOUT) -> bool:
        """Establish a link to the server.

        Args:
            timeout: How long to wait for the link (seconds).

        Returns:
            True if the link was established.
        """
        if self.link and self.link.status == RNS.Link.ACTIVE:
            return True

        # Resolve the server's destination from its hash
        server_identity = RNS.Identity.recall(self.server_dest_hash)
        if not server_identity:
            # Request path to the destination
            RNS.Transport.request_path(self.server_dest_hash)
            # Wait for path resolution
            start = time.time()
            while time.time() - start < timeout:
                server_identity = RNS.Identity.recall(self.server_dest_hash)
                if server_identity:
                    break
                time.sleep(0.25)
            if not server_identity:
                return False

        # Build the destination and request a link
        server_dest = RNS.Destination(server_identity, RNS.Destination.OUT, APP_NAME, "sync")

        self.link = RNS.Link(server_dest)

        # Wait for the link to be established
        start = time.time()
        while time.time() - start < timeout:
            if self.link.status == RNS.Link.ACTIVE:
                self.link.set_packet_callback(self._packet_received)
                self.link.set_link_closed_callback(self._link_closed)
                if self.on_connected:
                    self.on_connected()
                return True
            if self.link.status == RNS.Link.CLOSED:
                self.link = None
                return False
            time.sleep(0.1)

        # Timed out
        if self.link:
            self.link.teardown()
            self.link = None
        return False

    def disconnect(self):
        """Tear down the link to the server."""
        if self.link and self.link.status == RNS.Link.ACTIVE:
            self.link.teardown()
        self.link = None

    def is_active(self) -> bool:
        """Check if the link is currently active."""
        return self.link is not None and self.link.status == RNS.Link.ACTIVE

    def send_and_receive(self, message: dict, timeout: float = RESPONSE_TIMEOUT) -> dict:
        """Send a message and wait for the server's response.

        This is the send_fn passed to SyncClient.full_sync(). It
        serializes the message, sends it over the link, and blocks
        until the server responds or the timeout expires.

        Args:
            message: Dict to send to the server.
            timeout: How long to wait for a response (seconds).

        Returns:
            The server's response dict, or None on timeout/error.
        """
        if not self.is_active():
            return None

        self._response = None
        self._response_event.clear()

        payload = json.dumps(message).encode("utf-8")
        packet = RNS.Packet(self.link, payload)
        packet.send()

        # Block until response arrives or timeout
        if self._response_event.wait(timeout=timeout):
            return self._response
        return None

    def send_heartbeat(self, payload: dict):
        """Send a heartbeat packet (fire-and-forget, no response expected).

        Args:
            payload: Heartbeat data (timestamp, position, etc.).
        """
        if not self.is_active():
            return

        payload["type"] = "heartbeat"
        data = json.dumps(payload).encode("utf-8")
        packet = RNS.Packet(self.link, data)
        packet.send()

    # --- Internal callbacks ---

    def _packet_received(self, raw):
        """Called when a packet arrives from the server.

        If we're waiting for a response (send_and_receive), the message
        is delivered there. Otherwise it's a server-pushed message
        (lease_renewal, data_changed) routed to on_push_message.
        """
        try:
            message = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        # If send_and_receive is blocking, deliver as its response
        if not self._response_event.is_set():
            self._response = message
            self._response_event.set()
        elif self.on_push_message:
            # Server-initiated push (lease_renewal, data_changed, etc.)
            self.on_push_message(message)

    def _link_closed(self, link):
        """Called when the server link is torn down."""
        self.link = None
        # Unblock any waiting send_and_receive
        self._response_event.set()
        if self.on_disconnected:
            self.on_disconnected()
