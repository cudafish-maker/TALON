# talon/server/tile_server.py
# Map tile serving for clients.
#
# The server pre-caches map tiles for the area of operations (AO).
# When clients request tiles, the server serves them from its cache
# rather than each client downloading them independently.
#
# Tile serving is broadband-only — tiles are too large for LoRa.
# Clients using RNode get their map from whatever tiles they already
# have cached locally.
#
# Tile sources: OpenStreetMap, Satellite, Topography
# Tile format: Standard Web Mercator (z/x/y) PNG files

import os
from talon.sync.tiles import (
    tile_path,
    is_tile_cached,
    get_tiles_for_bounds,
    estimate_tile_count,
    TILE_SOURCES,
)


class TileServer:
    """Serves cached map tiles to clients.

    Attributes:
        cache_dir: Path to the server's tile cache directory.
    """

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir

    def get_tile(self, source: str, z: int, x: int, y: int) -> bytes:
        """Retrieve a cached tile.

        Args:
            source: Tile source key ("openstreetmap", "satellite", "topo").
            z: Zoom level.
            x: Tile column.
            y: Tile row.

        Returns:
            Raw PNG bytes, or None if the tile isn't cached.
        """
        path = tile_path(self.cache_dir, source, z, x, y)
        if not os.path.isfile(path):
            return None

        with open(path, "rb") as f:
            return f.read()

    def get_tile_list(self, source: str, bounds: dict,
                      min_zoom: int, max_zoom: int) -> list:
        """List all tiles needed for a given area and zoom range.

        Used when a client wants to know what tiles to request.

        Args:
            source: Tile source key.
            bounds: Dict with "north", "south", "east", "west" (decimal degrees).
            min_zoom: Lowest zoom level to include.
            max_zoom: Highest zoom level to include.

        Returns:
            List of (z, x, y) tuples for all tiles in the area.
        """
        all_tiles = []
        for z in range(min_zoom, max_zoom + 1):
            tiles = get_tiles_for_bounds(
                bounds["north"], bounds["south"],
                bounds["east"], bounds["west"], z
            )
            all_tiles.extend(tiles)
        return all_tiles

    def get_cached_tile_list(self, source: str, bounds: dict,
                             min_zoom: int, max_zoom: int) -> list:
        """List tiles that are already cached for a given area.

        Clients use this to figure out which tiles they still need.

        Args:
            source: Tile source key.
            bounds: Area bounds dict.
            min_zoom: Lowest zoom level.
            max_zoom: Highest zoom level.

        Returns:
            List of (z, x, y) tuples for cached tiles only.
        """
        needed = self.get_tile_list(source, bounds, min_zoom, max_zoom)
        cached = []
        for z, x, y in needed:
            if is_tile_cached(self.cache_dir, source, z, x, y):
                cached.append((z, x, y))
        return cached

    def estimate_download_size(self, source: str, bounds: dict,
                               min_zoom: int, max_zoom: int,
                               avg_tile_kb: int = 15) -> dict:
        """Estimate the download size for caching an area.

        Args:
            source: Tile source key.
            bounds: Area bounds dict.
            min_zoom: Lowest zoom level.
            max_zoom: Highest zoom level.
            avg_tile_kb: Average tile size in kilobytes (rough estimate).

        Returns:
            Dict with "tile_count" and "estimated_mb".
        """
        count = 0
        for z in range(min_zoom, max_zoom + 1):
            count += estimate_tile_count(
                bounds["north"], bounds["south"],
                bounds["east"], bounds["west"], z
            )

        estimated_mb = (count * avg_tile_kb) / 1024

        return {
            "tile_count": count,
            "estimated_mb": round(estimated_mb, 1),
        }

    def get_available_sources(self) -> dict:
        """Get all configured tile sources."""
        return dict(TILE_SOURCES)
