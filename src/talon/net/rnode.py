# talon/net/rnode.py
# RNode hardware lifecycle management.
#
# Handles detection, validation, and configuration of RNode LoRa
# radio hardware connected via USB serial. RNode devices are ESP32-
# based LoRa radios that Reticulum uses for off-grid mesh networking.
#
# Lifecycle:
#   1. detect()   — find connected RNode hardware
#   2. validate() — check serial port is accessible, probe for RNode
#   3. configure() — apply LoRa parameters from T.A.L.O.N. config
#   4. status()   — report current RNode state
#
# This module does NOT instantiate Reticulum interfaces directly.
# It prepares the configuration that Reticulum needs, and verifies
# the hardware is ready before Reticulum tries to open it.

import logging
import time

log = logging.getLogger(__name__)


# RNode firmware responds to these bytes on the serial port.
# Used to verify a device is actually running RNode firmware.
RNODE_PROBE_COMMAND = b"\xc0\x00\x00\xc0"  # KISS FEND + empty frame
RNODE_PROBE_TIMEOUT = 2.0  # seconds


class RNodeStatus:
    """Current state of RNode hardware."""
    DISCONNECTED = "disconnected"  # No RNode detected
    DETECTED = "detected"          # USB device found, not yet validated
    READY = "ready"                # Validated and ready for Reticulum
    ERROR = "error"                # Detected but not accessible
    IN_USE = "in_use"              # Reticulum has claimed the port


class RNodeManager:
    """Manages RNode hardware detection and configuration.

    Provides a high-level API for the rest of T.A.L.O.N. to interact
    with RNode hardware without needing to know serial port details.
    """

    def __init__(self, config: dict = None):
        """
        Args:
            config: The 'rnode' section from server.yaml or client.yaml.
                    If None, uses defaults.
        """
        self._config = config or {}
        self._status = RNodeStatus.DISCONNECTED
        self._port = None
        self._port_info = None
        self._error = None
        self._last_check = 0

    @property
    def status(self) -> str:
        return self._status

    @property
    def port(self) -> str:
        return self._port

    @property
    def error(self) -> str:
        return self._error

    @property
    def port_info(self) -> dict:
        return self._port_info

    def detect(self) -> bool:
        """Detect RNode hardware on available serial ports.

        Uses the configured port first (if set), then falls back to
        auto-detection via USB VID:PID matching.

        Returns:
            True if an RNode candidate was found.
        """
        from talon.platform import detect_rnode_ports, check_serial_port

        # If a specific port is configured, check it first
        configured_port = self._config.get("port", "")
        if configured_port:
            check = check_serial_port(configured_port)
            if check["exists"]:
                self._port = configured_port
                self._port_info = {"port": configured_port,
                                   "description": "configured",
                                   "hwid": ""}
                self._status = RNodeStatus.DETECTED
                log.info("RNode: using configured port %s", configured_port)
                return True

        # Auto-detect from available serial ports
        candidates = detect_rnode_ports()
        if candidates:
            best = candidates[0]
            self._port = best["port"]
            self._port_info = best
            self._status = RNodeStatus.DETECTED
            log.info("RNode: auto-detected %s (%s)",
                     best["port"], best.get("description", ""))
            return True

        self._status = RNodeStatus.DISCONNECTED
        self._port = None
        self._port_info = None
        log.info("RNode: no hardware detected")
        return False

    def validate(self) -> bool:
        """Validate the detected serial port is accessible.

        Checks that the port can be opened and optionally probes
        for RNode firmware response.

        Returns:
            True if the port is ready for use.
        """
        if not self._port:
            self._error = "No port detected"
            self._status = RNodeStatus.DISCONNECTED
            return False

        from talon.platform import check_serial_port
        check = check_serial_port(self._port)

        if not check["accessible"]:
            self._error = check["error"]
            self._status = RNodeStatus.ERROR
            log.warning("RNode: port %s not accessible: %s",
                        self._port, self._error)
            return False

        # Port is accessible — try a firmware probe
        if self._probe_firmware():
            self._status = RNodeStatus.READY
            self._error = None
            log.info("RNode: %s validated and ready", self._port)
            return True

        # Probe failed but port opens — could still be RNode with
        # non-responsive firmware, or the port is claimed by another
        # process. Mark as ready anyway since Reticulum will handle
        # the actual RNode protocol handshake.
        self._status = RNodeStatus.READY
        self._error = None
        log.info("RNode: %s accessible (firmware probe inconclusive)",
                 self._port)
        return True

    def _probe_firmware(self) -> bool:
        """Send a KISS probe to check if device responds like an RNode.

        Returns:
            True if the device appears to be running RNode firmware.
        """
        try:
            import serial
            ser = serial.Serial(
                self._port, baudrate=115200,
                timeout=RNODE_PROBE_TIMEOUT
            )
            # Flush any stale data
            ser.reset_input_buffer()
            # Send KISS frame boundary — RNode firmware echoes or
            # responds with its own KISS frames
            ser.write(RNODE_PROBE_COMMAND)
            time.sleep(0.5)
            response = ser.read(ser.in_waiting or 1)
            ser.close()

            # Any response suggests active firmware
            if response and len(response) > 0:
                log.debug("RNode probe got %d bytes from %s",
                          len(response), self._port)
                return True
            return False
        except Exception as exc:
            log.debug("RNode probe failed on %s: %s", self._port, exc)
            return False

    def get_interface_config(self) -> dict:
        """Build the Reticulum RNodeInterface configuration.

        Merges detected port with LoRa parameters from the T.A.L.O.N.
        config. This dict is ready to pass to Reticulum's config.

        Returns:
            Dict with RNodeInterface parameters, or empty dict if
            no RNode is available.
        """
        if self._status not in (RNodeStatus.READY, RNodeStatus.DETECTED):
            return {}

        port = self._port or self._config.get("port", "/dev/ttyUSB0")

        return {
            "type": "RNodeInterface",
            "interface_enabled": True,
            "port": port,
            "frequency": self._config.get("frequency", 915000000),
            "bandwidth": self._config.get("bandwidth", 125000),
            "spreading_factor": self._config.get("spreading_factor", 10),
            "coding_rate": self._config.get("coding_rate", 5),
            "txpower": self._config.get("tx_power", 17),
        }

    def get_status_summary(self) -> dict:
        """Get a summary of the RNode status for display in the UI.

        Returns:
            Dict with status, port, error, and radio parameters.
        """
        summary = {
            "status": self._status,
            "port": self._port,
            "error": self._error,
        }
        if self._port_info:
            summary["device"] = self._port_info.get("description", "")
            summary["manufacturer"] = self._port_info.get("manufacturer", "")
        if self._status in (RNodeStatus.READY, RNodeStatus.IN_USE):
            summary["frequency_mhz"] = self._config.get(
                "frequency", 915000000) / 1_000_000
            summary["bandwidth_khz"] = self._config.get(
                "bandwidth", 125000) / 1_000
            summary["spreading_factor"] = self._config.get(
                "spreading_factor", 10)
            summary["tx_power_dbm"] = self._config.get("tx_power", 17)
        return summary

    def mark_in_use(self):
        """Mark the RNode as claimed by Reticulum."""
        if self._status == RNodeStatus.READY:
            self._status = RNodeStatus.IN_USE

    def mark_disconnected(self):
        """Mark the RNode as disconnected (e.g., USB unplugged)."""
        self._status = RNodeStatus.DISCONNECTED
        self._port = None
        self._port_info = None
