# talon/server/cli.py
# CLI entry point for the T.A.L.O.N. server.
#
# Installed as `talon-server` via pyproject.toml console_scripts.
# Also used by talon-server.py for direct execution.

import argparse


def main():
    parser = argparse.ArgumentParser(description="T.A.L.O.N. Server — Tactical Awareness & Linked Operations Network")
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
