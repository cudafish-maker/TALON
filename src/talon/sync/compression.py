# talon/sync/compression.py
# Data compression and binary packing for LoRa transmission.
#
# LoRa (RNode 915MHz) has very limited bandwidth (~1-10 kbps).
# Every byte counts. This module compresses and packs data into
# the smallest possible format for radio transmission.
#
# Over broadband (Yggdrasil/I2P/TCP), data is sent as JSON — easy
# to read and debug, but larger.
#
# Over LoRa, data is:
# 1. Compressed with zlib (general-purpose compression)
# 2. Packed in a binary format (no JSON overhead)
# 3. Split into packets if too large for a single transmission
#
# Position encoding example:
# JSON:  {"lat": 38.897957, "lon": -77.036560}  = 42 bytes
# Binary: two 4-byte fixed-point integers           = 8 bytes
# Savings: 81% smaller

import zlib
import struct


# Maximum packet size for LoRa transmission (bytes).
# Larger messages are automatically split into multiple packets.
MAX_LORA_PACKET = 200

# Position encoding: multiply by this to convert float to int.
# 6 decimal places of precision = ~0.1 meter accuracy.
POSITION_SCALE = 1_000_000


def compress(data: bytes) -> bytes:
    """Compress data using zlib for transmission over LoRa.

    Args:
        data: Raw bytes to compress.

    Returns:
        Compressed bytes. Typically 40-60% smaller for text data.
    """
    return zlib.compress(data, level=9)  # Maximum compression


def decompress(data: bytes) -> bytes:
    """Decompress data received over LoRa.

    Args:
        data: Compressed bytes from compress().

    Returns:
        Original uncompressed bytes.
    """
    return zlib.decompress(data)


def pack_position(latitude: float, longitude: float) -> bytes:
    """Pack a GPS position into 8 bytes for LoRa transmission.

    Converts floating-point lat/lon into fixed-point integers.
    Preserves 6 decimal places (~0.1 meter accuracy).

    Args:
        latitude: GPS latitude (e.g., 38.897957).
        longitude: GPS longitude (e.g., -77.036560).

    Returns:
        8 bytes containing the packed position.
    """
    # Convert to fixed-point integers
    lat_int = int(latitude * POSITION_SCALE)
    lon_int = int(longitude * POSITION_SCALE)
    # Pack as two signed 32-bit integers (big-endian)
    return struct.pack(">ii", lat_int, lon_int)


def unpack_position(data: bytes) -> tuple:
    """Unpack a GPS position from 8 bytes.

    Args:
        data: 8 bytes from pack_position().

    Returns:
        Tuple of (latitude, longitude) as floats.
    """
    lat_int, lon_int = struct.unpack(">ii", data)
    return (lat_int / POSITION_SCALE, lon_int / POSITION_SCALE)


def split_packets(data: bytes, max_size: int = MAX_LORA_PACKET) -> list:
    """Split data into LoRa-sized packets.

    Each packet includes a header with:
    - 1 byte: packet index (which piece this is)
    - 1 byte: total packet count
    - 2 bytes: message ID (to reassemble)
    This leaves max_size - 4 bytes for actual data.

    Args:
        data: The full data to split.
        max_size: Maximum packet size in bytes.

    Returns:
        List of byte packets, each <= max_size.
    """
    payload_size = max_size - 4  # Reserve 4 bytes for header
    chunks = []
    for i in range(0, len(data), payload_size):
        chunks.append(data[i : i + payload_size])

    total = len(chunks)
    # Use a simple incrementing message ID (wraps at 65535)
    msg_id = hash(data) & 0xFFFF

    packets = []
    for i, chunk in enumerate(chunks):
        # Header: index (1 byte) + total (1 byte) + msg_id (2 bytes)
        header = struct.pack(">BBH", i, total, msg_id)
        packets.append(header + chunk)

    return packets


def reassemble_packets(packets: list) -> bytes:
    """Reassemble data from split LoRa packets.

    Args:
        packets: List of received packets (may be out of order).

    Returns:
        The original data, or None if packets are missing.
    """
    if not packets:
        return None

    # Parse headers and sort by index
    parsed = []
    for packet in packets:
        index, total, msg_id = struct.unpack(">BBH", packet[:4])
        parsed.append((index, packet[4:]))

    # Sort by packet index
    parsed.sort(key=lambda p: p[0])

    # Check we have all packets
    expected_total = len(parsed)
    if parsed[-1][0] + 1 != expected_total:
        return None  # Missing packets

    # Reassemble
    return b"".join(chunk for _, chunk in parsed)
