# tests/test_sync.py
# Tests for the sync layer (protocol, priority, compression, outbox, tiles).

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.sync.priority import sort_by_priority, filter_for_transport, BROADBAND_ONLY
from talon.constants import TransportType
from talon.sync.compression import (
    compress, decompress,
    pack_position, unpack_position,
    split_packets, reassemble_packets,
)
from talon.sync.outbox import Outbox
from talon.sync.tiles import lat_lon_to_tile, estimate_tile_count, is_tile_cached


# ---------- Priority ----------

def test_sort_by_priority():
    """Higher priority tables should come first."""
    data_types = ["map_tiles", "operators", "sitreps"]
    sorted_types = sort_by_priority(data_types)
    # sitreps (priority 4) should come before operators (priority 8)
    # operators (priority 8) should come before map_tiles (priority 10)
    assert sorted_types.index("operators") < sorted_types.index("map_tiles")
    assert sorted_types.index("sitreps") < sorted_types.index("operators")


def test_filter_for_lora():
    """Broadband-only tables should be removed for LoRa."""
    data_types = ["operators", "documents", "sitreps"]
    filtered = filter_for_transport(data_types, TransportType.RNODE)
    assert "documents" not in filtered
    assert "operators" in filtered
    assert "sitreps" in filtered


def test_filter_for_broadband_keeps_all():
    """Broadband should keep all tables."""
    data_types = ["operators", "documents"]
    filtered = filter_for_transport(data_types, TransportType.YGGDRASIL)
    assert "documents" in filtered
    assert "operators" in filtered


# ---------- Compression ----------

def test_compress_decompress():
    """Compress → decompress should return original data."""
    original = b"This is test data for compression " * 10
    compressed = compress(original)
    decompressed = decompress(compressed)
    assert decompressed == original
    assert len(compressed) < len(original)  # Should actually compress


def test_position_packing():
    """Pack → unpack should preserve GPS coordinates within tolerance."""
    lat, lon = 34.052235, -118.243683
    packed = pack_position(lat, lon)
    assert len(packed) == 8  # 4 bytes lat + 4 bytes lon

    ulat, ulon = unpack_position(packed)
    # Should be accurate to ~0.1 metre
    assert abs(ulat - lat) < 0.000001
    assert abs(ulon - lon) < 0.000001


def test_packet_splitting():
    """Large data should split into LoRa-sized packets and reassemble."""
    data = os.urandom(500)  # Bigger than one LoRa packet (200 bytes)
    packets = split_packets(data)
    assert len(packets) > 1  # Should need multiple packets

    reassembled = reassemble_packets(packets)
    assert reassembled == data


def test_single_packet_no_split():
    """Small data should fit in one packet."""
    data = b"short"
    packets = split_packets(data)
    assert len(packets) == 1

    reassembled = reassemble_packets(packets)
    assert reassembled == data


# ---------- Outbox ----------

def test_outbox_add_and_get():
    outbox = Outbox()
    outbox.add("sitreps", "insert", {"id": "s1", "content": "test"})
    outbox.add("sitreps", "insert", {"id": "s2", "content": "test2"})
    outbox.add("assets", "insert", {"id": "a1", "name": "cache"})

    pending = outbox.get_pending()
    assert len(pending) == 3
    assert pending[0]["table"] == "sitreps"
    assert pending[2]["table"] == "assets"


def test_outbox_count():
    outbox = Outbox()
    assert outbox.count() == 0

    outbox.add("sitreps", "insert", {"id": "s1"})
    outbox.add("assets", "insert", {"id": "a1"})
    assert outbox.count() == 2


def test_outbox_clear():
    outbox = Outbox()
    outbox.add("sitreps", "insert", {"id": "s1"})
    outbox.clear()
    assert outbox.count() == 0


def test_outbox_json_roundtrip():
    """Outbox should survive serialization to/from JSON."""
    outbox = Outbox()
    outbox.add("sitreps", "insert", {"id": "s1", "content": "test"})
    outbox.add("assets", "insert", {"id": "a1", "name": "cache"})

    json_str = outbox.to_json()
    restored = Outbox()
    restored.from_json(json_str)

    assert restored.count() == 2
    pending = restored.get_pending()
    assert pending[0]["table"] == "sitreps"
    assert pending[1]["table"] == "assets"


# ---------- Tiles ----------

def test_lat_lon_to_tile():
    """Known coordinate should produce a valid tile."""
    x, y = lat_lon_to_tile(34.052235, -118.243683, 10)
    assert x > 0
    assert y > 0


def test_estimate_tile_count():
    """A small area at low zoom should have a reasonable tile count."""
    count = estimate_tile_count(34.1, 33.9, -118.1, -118.4, 10, 10)
    assert count > 0
    assert count < 100  # Should be just a few tiles at zoom 10


def test_tile_not_cached():
    """A tile in a nonexistent directory should not be cached."""
    assert is_tile_cached("/nonexistent/path", "openstreetmap", 10, 1, 1) is False
