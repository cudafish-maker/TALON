#!/usr/bin/env python3
# talon-client.py
# T.A.L.O.N. client launcher.
#
# Usage:
#   python talon-client.py
#   python talon-client.py --config /path/to/config/dir

import sys
import os
import argparse

# Ensure the src/ directory is on the Python path so talon.* imports work
# whether running directly or via PyInstaller bundle.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def main():
    parser = argparse.ArgumentParser(
        description="T.A.L.O.N. — Tactical Awareness & Linked Operations Network"
    )
    parser.add_argument(
        "--config",
        metavar="DIR",
        default=None,
        help="Path to the config directory (default: ./config)",
    )
    args = parser.parse_args()

    from talon.ui.app import run_client
    run_client(config_path=args.config)


if __name__ == "__main__":
    main()
