"""Focused tests for shared network framing."""
import base64

from talon.network import framing
from talon.network import protocol as proto


class _FakePacket:
    def __init__(self, sent, link, data):
        self._sent = sent
        self.link = link
        self.data = data

    def send(self):
        self._sent.append((self.link, self.data))


def _patch_packet(monkeypatch, sent):
    monkeypatch.setattr(
        framing.RNS,
        "Packet",
        lambda link, data: _FakePacket(sent, link, data),
    )


def _chunk_msg(msg_id, seq, total, data):
    return {
        "type": proto.MSG_CHUNK,
        "id": msg_id,
        "seq": seq,
        "total": total,
        "data": base64.b64encode(data).decode(),
    }


def test_smart_send_packet_size_boundary_uses_single_packet(monkeypatch):
    sent = []
    link = object()
    payload = b"x" * framing.PACKET_MAX
    _patch_packet(monkeypatch, sent)

    framing.smart_send(link, payload)

    assert sent == [(link, payload)]


def test_smart_send_chunks_payload_over_packet_boundary(monkeypatch):
    sent = []
    link = object()
    payload = b"x" * (framing.PACKET_MAX + 1)
    _patch_packet(monkeypatch, sent)

    framing.smart_send(link, payload)

    assert len(sent) == 2
    chunks = [proto.decode(data) for _, data in sent]
    assert {chunk["id"] for chunk in chunks} == {chunks[0]["id"]}
    assert [chunk["seq"] for chunk in chunks] == [0, 1]
    assert [chunk["total"] for chunk in chunks] == [2, 2]
    assert all(len(data) <= framing.PACKET_MAX for _, data in sent)

    reassembler = framing.ChunkReassembler()
    assert reassembler.handle(chunks[0]) is None
    assert reassembler.handle(chunks[1]) == payload


def test_reassembler_accepts_out_of_order_chunks():
    reassembler = framing.ChunkReassembler()
    msg_id = "out-of-order"

    assert reassembler.handle(_chunk_msg(msg_id, 2, 3, b"cc")) is None
    assert reassembler.handle(_chunk_msg(msg_id, 0, 3, b"aa")) is None
    assert reassembler.handle(_chunk_msg(msg_id, 1, 3, b"bb")) == b"aabbcc"
    assert reassembler.buffers == {}


def test_reassembler_ignores_duplicate_chunks_without_corrupting_buffer():
    reassembler = framing.ChunkReassembler()
    msg_id = "duplicate"

    assert reassembler.handle(_chunk_msg(msg_id, 0, 2, b"aa")) is None
    assert reassembler.handle(_chunk_msg(msg_id, 0, 2, b"changed")) is None
    assert reassembler.handle(_chunk_msg(msg_id, 1, 2, b"bb")) == b"aabb"
    assert reassembler.buffers == {}


def test_reassembler_gc_removes_stale_buffers():
    now = [100.0]
    reassembler = framing.ChunkReassembler(ttl_s=10.0, time_func=lambda: now[0])

    assert reassembler.handle(_chunk_msg("stale", 0, 2, b"aa")) is None
    assert "stale" in reassembler.buffers

    now[0] = 111.0
    assert reassembler.gc() == 1
    assert reassembler.buffers == {}


def test_reassembler_buffer_cap_drops_oldest_buffer():
    now = [0.0]
    reassembler = framing.ChunkReassembler(
        max_buffers=2,
        time_func=lambda: now[0],
    )

    now[0] = 1.0
    assert reassembler.handle(_chunk_msg("first", 0, 2, b"aa")) is None
    now[0] = 2.0
    assert reassembler.handle(_chunk_msg("second", 0, 2, b"bb")) is None
    now[0] = 3.0
    assert reassembler.handle(_chunk_msg("third", 0, 2, b"cc")) is None

    assert set(reassembler.buffers) == {"second", "third"}
