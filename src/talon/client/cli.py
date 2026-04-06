# talon/client/cli.py
# CLI entry point for the T.A.L.O.N. client.
#
# Installed as `talon-client` via pyproject.toml console_scripts.
# Also used by talon-client.py for direct execution.

import argparse


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
