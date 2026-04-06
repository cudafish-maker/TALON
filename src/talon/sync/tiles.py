# talon/sync/tiles.py
# Map tile pre-caching and sync for T.A.L.O.N.
#
# Map tiles are small image files that, when stitched together,
# form the map the operator sees. Three layer types are supported:
# - OpenStreetMap (roads, buildings, landmarks)
# - Satellite (aerial/space imagery)
# - Topography (elevation contours, terrain)
#
# Tile caching workflow:
# 1. Server operator draws an AO (Area of Operations) bounding box
# 2. Server downloads all tiles for that area at specified zoom levels
# 3. Tiles are stored on the server
# 4. Clients download the tile bundle over broadband during sync
# 5. Once cached, the map works fully even over LoRa (no new downloads)
#
# Tiles use the standard "slippy map" format: zoom/x/y.png
# At zoom level 10, the whole world is ~1 million tiles.
# A typical AO at zoom 10-17 might be 5,000-50,000 tiles.

import math
import os

# Tile sources — URLs that serve map tile images.
# {z} = zoom level, {x} = column, {y} = row
TILE_SOURCES = {
    "openstreetmap": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "satellite": "",  # To be configured (e.g., ESRI, Mapbox)
    "topography": "",  # To be configured (e.g., OpenTopoMap)
}


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple:
    """Convert GPS coordinates to tile coordinates.

    Given a latitude, longitude, and zoom level, calculates which
    tile contains that point. This is standard Web Mercator math.

    Args:
        lat: GPS latitude in degrees.
        lon: GPS longitude in degrees.
        zoom: Zoom level (0-19). Higher = more detail, more tiles.

    Returns:
        Tuple of (x, y) tile coordinates.
    """
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return (x, y)


def get_tiles_for_bounds(
    north: float,
    south: float,
    east: float,
    west: float,
    zoom_min: int,
    zoom_max: int,
) -> list:
    """Calculate all tile coordinates needed for a bounding box.

    Given the corners of the AO and a range of zoom levels,
    returns every tile that needs to be downloaded.

    Args:
        north: Northern latitude boundary.
        south: Southern latitude boundary.
        east: Eastern longitude boundary.
        west: Western longitude boundary.
        zoom_min: Minimum zoom level to cache (e.g., 10).
        zoom_max: Maximum zoom level to cache (e.g., 17).

    Returns:
        List of (zoom, x, y) tuples for every required tile.
    """
    tiles = []
    for zoom in range(zoom_min, zoom_max + 1):
        # Get tile coordinates for the corners
        x_min, y_min = lat_lon_to_tile(north, west, zoom)
        x_max, y_max = lat_lon_to_tile(south, east, zoom)
        # Collect all tiles in the rectangle
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                tiles.append((zoom, x, y))
    return tiles


def estimate_tile_count(
    north: float,
    south: float,
    east: float,
    west: float,
    zoom_min: int,
    zoom_max: int,
) -> int:
    """Estimate how many tiles will need to be downloaded.

    Useful for showing the server operator how large the download
    will be before they commit to it.

    Args:
        Same as get_tiles_for_bounds().

    Returns:
        Total number of tiles across all zoom levels.
    """
    return len(get_tiles_for_bounds(north, south, east, west, zoom_min, zoom_max))


def tile_path(cache_dir: str, layer: str, zoom: int, x: int, y: int) -> str:
    """Get the local file path for a cached tile.

    Tiles are stored in a directory structure:
    cache_dir/layer/zoom/x/y.png

    Args:
        cache_dir: Base directory for tile storage.
        layer: "openstreetmap", "satellite", or "topography".
        zoom: Zoom level.
        x: Tile X coordinate.
        y: Tile Y coordinate.

    Returns:
        Full file path for the tile image.
    """
    return os.path.join(cache_dir, layer, str(zoom), str(x), f"{y}.png")


def is_tile_cached(cache_dir: str, layer: str, zoom: int, x: int, y: int) -> bool:
    """Check if a specific tile is already cached locally.

    Args:
        Same as tile_path().

    Returns:
        True if the tile file exists on disk.
    """
    return os.path.exists(tile_path(cache_dir, layer, zoom, x, y))
