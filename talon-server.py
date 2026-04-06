#!/usr/bin/env python3
# talon-server.py
# T.A.L.O.N. server launcher — "the chair".
#
# Usage:
#   python talon-server.py
#   python talon-server.py --config /path/to/config/dir

import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Suppress Kivy's clipboard provider search — the server has no clipboard needs.
# Must be set before any kivy import to take effect.
os.environ.setdefault("KIVY_CLIPBOARD", "dummy")


def main():
    parser = argparse.ArgumentParser(
        description="T.A.L.O.N. Server — Tactical Awareness & Linked Operations Network"
    )
    parser.add_argument(
        "--config",
        metavar="DIR",
        default=None,
        help="Path to the config directory (default: ./config)",
    )
    args = parser.parse_args()

    from talon.ui.server.app import run_server
    run_server(config_path=args.config)


if __name__ == "__main__":
    main()
