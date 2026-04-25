# KIVY_NO_ENV_CONFIG must be set before any Kivy import.
import os
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")

import logging
import sys

# Configure root logger before importing any talon module (which attaches a
# NullHandler to the 'talon' logger and defers format/level to the entry point).
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)

from talon.config import get_mode, load_config
from talon.utils.logging import get_logger

_log = get_logger("main")

# Desktop platforms: disable Kivy's multi-touch simulation (right-click red dots).
# Must be done before any Kivy Window / App import.
_DESKTOP_PLATFORMS = ("linux", "win32", "darwin", "cygwin")
if sys.platform in _DESKTOP_PLATFORMS:
    from kivy.config import Config  # noqa: E402
    Config.set("input", "mouse", "mouse,disable_multitouch")


def main() -> None:
    cfg = load_config()
    mode = get_mode(cfg)

    # Wire operator-configured TCP probe endpoints before any network calls,
    # so high-OPSEC deployments don't contact public DNS (8.8.8.8 etc.).
    from talon.network.interfaces import configure_tcp_probe_endpoints
    hosts = cfg.get("network", "tcp_probe_hosts", fallback="").strip()
    if hosts:
        configure_tcp_probe_endpoints(hosts)

    _log.info("Starting T.A.L.O.N. in %s mode", mode)

    from talon.app import TalonApp
    TalonApp(mode=mode, cfg=cfg).run()


if __name__ == "__main__":
    main()
