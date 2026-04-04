#!/usr/bin/env python3
# tools/tile_prefetch.py
# Pre-download map tiles for an area of operations (AO).
#
# Before deploying to the field, run this tool to cache map tiles
# for the AO. This ensures all operators have map data even if they
# are only connected via RNode (tiles can't be downloaded over LoRa).
#
# Usage:
#   python tools/tile_prefetch.py --north 34.1 --south 33.9 --east -118.1 --west -118.4
#   python tools/tile_prefetch.py --north 34.1 --south 33.9 --east -118.1 --west -118.4 --zoom 8-15
#   python tools/tile_prefetch.py --north 34.1 --south 33.9 --east -118.1 --west -118.4 --source satellite
#   python tools/tile_prefetch.py --estimate-only --north 34.1 --south 33.9 --east -118.1 --west -118.4
#
# Tile sources: openstreetmap, satellite, topo
# Default zoom range: 8-16 (good balance of coverage and detail)

import argparse
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.sync.tiles import (
    TILE_SOURCES,
    get_tiles_for_bounds,
    estimate_tile_count,
    tile_path,
    is_tile_cached,
)


def download_tile(source_key: str, z: int, x: int, y: int,
                  cache_dir: str) -> bool:
    """Download a single tile and save it to the cache.

    Args:
        source_key: Which tile source ("openstreetmap", "satellite", "topo").
        z, x, y: Tile coordinates.
        cache_dir: Where to save the tile file.

    Returns:
        True if downloaded successfully, False on error.
    """
    source = TILE_SOURCES.get(source_key, {})
    url_template = source.get("url", "")
    if not url_template:
        print(f"  ERROR: No URL template for source '{source_key}'")
        return False

    # Build the tile URL from the template
    url = url_template.format(z=z, x=x, y=y)

    # Build the local file path
    path = tile_path(cache_dir, source_key, z, x, y)

    # Create directories if needed
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        # Download the tile with a user-agent header (required by most
        # tile servers to identify the application)
        req = urllib.request.Request(url, headers={
            "User-Agent": "TALON-TilePrefetch/0.1"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()

        # Save to disk
        with open(path, "wb") as f:
            f.write(data)

        return True

    except Exception as e:
        print(f"  ERROR downloading z={z} x={x} y={y}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Pre-download map tiles for a T.A.L.O.N. area of operations."
    )
    parser.add_argument("--north", type=float, required=True,
                        help="Northern boundary (latitude, decimal degrees).")
    parser.add_argument("--south", type=float, required=True,
                        help="Southern boundary (latitude, decimal degrees).")
    parser.add_argument("--east", type=float, required=True,
                        help="Eastern boundary (longitude, decimal degrees).")
    parser.add_argument("--west", type=float, required=True,
                        help="Western boundary (longitude, decimal degrees).")
    parser.add_argument("--zoom", type=str, default="8-16",
                        help="Zoom range, e.g. '8-16' (default: 8-16).")
    parser.add_argument("--source", type=str, default="openstreetmap",
                        choices=list(TILE_SOURCES.keys()),
                        help="Tile source (default: openstreetmap).")
    parser.add_argument("--all-sources", action="store_true",
                        help="Download from ALL tile sources.")
    parser.add_argument("--cache-dir", type=str, default="data/tiles",
                        help="Where to save tiles (default: data/tiles).")
    parser.add_argument("--estimate-only", action="store_true",
                        help="Just show how many tiles and estimated size.")
    parser.add_argument("--delay", type=float, default=0.1,
                        help="Seconds between downloads to be polite to "
                             "tile servers (default: 0.1).")
    args = parser.parse_args()

    # Parse zoom range
    if "-" in args.zoom:
        min_zoom, max_zoom = map(int, args.zoom.split("-"))
    else:
        min_zoom = max_zoom = int(args.zoom)

    # Decide which sources to download
    sources = list(TILE_SOURCES.keys()) if args.all_sources else [args.source]

    # Calculate total tiles needed
    total_tiles = 0
    for z in range(min_zoom, max_zoom + 1):
        total_tiles += estimate_tile_count(
            args.north, args.south, args.east, args.west, z
        )
    total_tiles *= len(sources)

    # Estimate size (rough: ~15KB per tile on average)
    estimated_mb = (total_tiles * 15) / 1024

    print(f"\n  T.A.L.O.N. Tile Prefetch")
    print(f"  Area: N{args.north} S{args.south} E{args.east} W{args.west}")
    print(f"  Zoom: {min_zoom}-{max_zoom}")
    print(f"  Sources: {', '.join(sources)}")
    print(f"  Total tiles: {total_tiles:,}")
    print(f"  Estimated size: ~{estimated_mb:,.1f} MB\n")

    if args.estimate_only:
        return

    # Download tiles
    downloaded = 0
    skipped = 0
    failed = 0
    start_time = time.time()

    for source_key in sources:
        print(f"  Downloading {source_key} tiles...")

        for z in range(min_zoom, max_zoom + 1):
            tiles = get_tiles_for_bounds(
                args.north, args.south, args.east, args.west, z
            )

            for tz, tx, ty in tiles:
                # Skip if already cached
                if is_tile_cached(args.cache_dir, source_key, tz, tx, ty):
                    skipped += 1
                    continue

                success = download_tile(source_key, tz, tx, ty, args.cache_dir)
                if success:
                    downloaded += 1
                else:
                    failed += 1

                # Progress update every 100 tiles
                done = downloaded + skipped + failed
                if done % 100 == 0:
                    elapsed = time.time() - start_time
                    print(f"    Progress: {done}/{total_tiles} "
                          f"({elapsed:.0f}s elapsed)")

                # Polite delay between downloads
                if args.delay > 0:
                    time.sleep(args.delay)

    elapsed = time.time() - start_time
    print(f"\n  Done in {elapsed:.1f}s")
    print(f"  Downloaded: {downloaded}")
    print(f"  Already cached: {skipped}")
    print(f"  Failed: {failed}\n")


if __name__ == "__main__":
    main()
