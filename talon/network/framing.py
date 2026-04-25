"""
Shared RNS packet framing helpers.

TALON wire messages are JSON bytes.  Small messages fit in a single RNS packet;
larger messages are split into protocol ``chunk`` packets and reassembled by the
receiver before normal protocol dispatch.
"""
import base64
import os
import threading
import time
import typing

import RNS

from talon.network import protocol as proto
from talon.utils.logging import get_logger

_log = get_logger("network.framing")

# RNS.Packet hard limit on established encrypted links.  Payloads above this
# are chunked into MSG_CHUNK fragments, each of which carries CHUNK_SIZE bytes
# of raw payload.  200 bytes of raw data -> ~268 chars of base64 -> ~329 bytes
# total JSON per chunk, safely below PACKET_MAX.
PACKET_MAX = 380
CHUNK_SIZE = 200
CHUNK_BUFFER_TTL_S = 60.0
CHUNK_MAX_TOTAL = 4096
CHUNK_MAX_BUFFERS = 50


def smart_send(link: RNS.Link, data: bytes, *, logger=None) -> None:
    """Send *data* on *link*, chunking into MSG_CHUNK packets when needed."""
    log = logger or _log
    if len(data) <= PACKET_MAX:
        try:
            RNS.Packet(link, data).send()
        except Exception as exc:
            log.warning("smart_send failed (%d bytes): %s", len(data), exc)
        return

    msg_id = os.urandom(4).hex()
    pieces = [data[i:i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
    total = len(pieces)
    for seq, piece in enumerate(pieces):
        pkt = proto.encode({
            "type": proto.MSG_CHUNK,
            "id": msg_id,
            "seq": seq,
            "total": total,
            "data": base64.b64encode(piece).decode(),
        })
        try:
            RNS.Packet(link, pkt).send()
        except Exception as exc:
            log.warning(
                "chunk %d/%d send failed (%d bytes): %s",
                seq,
                total - 1,
                len(pkt),
                exc,
            )
            return


class ChunkReassembler:
    """Thread-safe MSG_CHUNK reassembly with stale-buffer and count caps."""

    def __init__(
        self,
        *,
        ttl_s: float = CHUNK_BUFFER_TTL_S,
        max_total: int = CHUNK_MAX_TOTAL,
        max_buffers: int = CHUNK_MAX_BUFFERS,
        time_func: typing.Callable[[], float] = time.time,
        logger=None,
    ) -> None:
        self.ttl_s = ttl_s
        self.max_total = max_total
        self.max_buffers = max_buffers
        self._time = time_func
        self._log = logger or _log
        self.buffers: dict[str, dict[str, typing.Any]] = {}
        self.lock = threading.Lock()

    def gc(self) -> int:
        """Discard stale incomplete reassemblies and return the count removed."""
        cutoff = self._time() - self.ttl_s
        with self.lock:
            stale = [
                k for k, v in self.buffers.items()
                if v.get("created_at", 0) < cutoff
            ]
            for k in stale:
                del self.buffers[k]
        if stale:
            self._log.debug("Chunk GC removed %d stale buffer(s)", len(stale))
        return len(stale)

    def handle(self, msg: dict) -> typing.Optional[bytes]:
        """
        Buffer a MSG_CHUNK fragment.

        Returns the reassembled payload bytes once all fragments for the message
        have arrived, otherwise returns None.
        """
        msg_id = msg.get("id", "")
        seq = msg.get("seq")
        total = msg.get("total")
        if not isinstance(msg_id, str) or not msg_id or len(msg_id) > 128:
            return None
        try:
            seq = int(seq)
            total = int(total)
        except (TypeError, ValueError):
            self._log.warning(
                "Invalid chunk metadata id=%s seq=%r total=%r",
                msg_id,
                msg.get("seq"),
                msg.get("total"),
            )
            return None
        if total < 1 or total > self.max_total or seq < 0 or seq >= total:
            self._log.warning(
                "Out-of-range chunk metadata id=%s seq=%s total=%s",
                msg_id,
                seq,
                total,
            )
            return None
        try:
            chunk_bytes = base64.b64decode(msg.get("data", ""), validate=True)
        except Exception:
            self._log.warning("Invalid base64 in chunk id=%s seq=%s", msg_id, seq)
            return None

        with self.lock:
            if msg_id not in self.buffers and len(self.buffers) >= self.max_buffers:
                oldest = min(
                    self.buffers,
                    key=lambda k: self.buffers[k].get("created_at", 0),
                )
                del self.buffers[oldest]
                self._log.warning(
                    "Chunk buffer cap reached; dropped oldest buffer id=%s",
                    oldest,
                )
            if msg_id not in self.buffers:
                self.buffers[msg_id] = {
                    "seqs": {},
                    "total": total,
                    "created_at": self._time(),
                }
            state = self.buffers[msg_id]
            if state.get("total") != total:
                del self.buffers[msg_id]
                self._log.warning("Chunk total changed mid-stream id=%s", msg_id)
                return None
            buf = state["seqs"]
            if seq in buf:
                self._log.warning("Duplicate chunk ignored id=%s seq=%s", msg_id, seq)
                return None
            buf[seq] = chunk_bytes
            if len(buf) == total:
                del self.buffers[msg_id]
                try:
                    return b"".join(buf[i] for i in range(total))
                except KeyError:
                    self._log.warning("Chunk reassembly missing fragment id=%s", msg_id)
                    return None
            return None
