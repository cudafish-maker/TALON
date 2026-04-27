"""
RNS Link lifecycle management.

Wraps RNS.Link creation, callback registration, and teardown.
All link state is managed here so callers don't need to interact
with RNS link internals directly.
"""
import typing

import RNS

from talon_core.utils.logging import get_logger

_log = get_logger("network.links")

LinkCallback = typing.Callable[[RNS.Link], None]
PacketCallback = typing.Callable[[bytes, RNS.Packet], None]


def open_link(
    destination: RNS.Destination,
    on_established: typing.Optional[LinkCallback] = None,
    on_closed: typing.Optional[LinkCallback] = None,
    on_packet: typing.Optional[PacketCallback] = None,
) -> RNS.Link:
    """Open a link to a remote destination and register callbacks."""
    link = RNS.Link(destination)

    if on_established:
        link.set_link_established_callback(on_established)
    if on_closed:
        link.set_link_closed_callback(on_closed)
    if on_packet:
        link.set_packet_callback(on_packet)

    _log.debug("Link opened to %s", RNS.prettyhexrep(destination.hash))
    return link


def close_link(link: RNS.Link) -> None:
    """Tear down a link gracefully."""
    try:
        link.teardown()
        _log.debug("Link torn down")
    except Exception as exc:
        _log.warning("Error closing link: %s", exc)


def send_packet(link: RNS.Link, data: bytes) -> None:
    """Send a data packet over an established link."""
    packet = RNS.Packet(link, data)
    packet.send()
