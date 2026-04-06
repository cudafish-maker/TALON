# tests/test_rnode.py
# Tests for RNode serial access, detection, and configuration wiring.
#
# Verifies:
# - Serial port enumeration returns expected format
# - RNode USB ID matching and scoring
# - RNodeManager lifecycle (detect, validate, status)
# - Reticulum config generation from T.A.L.O.N. YAML
# - Interface config merging with RNode override
# - Platform serial port checks
# - Android USB module guards

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# --- Serial port enumeration ------------------------------------------------


class TestSerialPortEnumeration:
    def test_list_serial_ports_returns_list(self):
        """list_serial_ports should always return a list."""
        from talon.platform import list_serial_ports

        result = list_serial_ports()
        assert isinstance(result, list)

    def test_list_serial_ports_entry_format(self):
        """Each entry should have the expected keys."""
        from talon.platform import list_serial_ports

        ports = list_serial_ports()
        for p in ports:
            assert "port" in p
            assert "description" in p
            assert "hwid" in p
            assert "vid" in p
            assert "pid" in p

    def test_detect_rnode_ports_returns_list(self):
        """detect_rnode_ports should always return a list."""
        from talon.platform import detect_rnode_ports

        result = detect_rnode_ports()
        assert isinstance(result, list)

    def test_get_default_serial_port_returns_string(self):
        """get_default_serial_port should return a non-empty string."""
        from talon.platform import get_default_serial_port

        port = get_default_serial_port()
        assert isinstance(port, str)
        assert len(port) > 0


# --- RNode USB ID matching --------------------------------------------------


class TestRNodeMatching:
    def test_known_cp2102_scores_high(self):
        """CP2102 (most common RNode chip) should score highly."""
        from talon.platform import _rnode_match_score

        port_info = {
            "vid": 0x10C4,
            "pid": 0xEA60,
            "description": "CP2102 USB to UART",
            "manufacturer": "Silicon Labs",
        }
        score = _rnode_match_score(port_info)
        assert score >= 15  # VID match (10) + PID match (5) + keyword

    def test_known_ch340_scores(self):
        """CH340 should score as a candidate."""
        from talon.platform import _rnode_match_score

        port_info = {
            "vid": 0x1A86,
            "pid": 0x7523,
            "description": "CH340 serial",
            "manufacturer": "QinHeng",
        }
        score = _rnode_match_score(port_info)
        assert score >= 15

    def test_official_rnode_vid_pid(self):
        """Official unsigned.io RNode VID:PID should score highest."""
        from talon.platform import _rnode_match_score

        port_info = {
            "vid": 0x1209,
            "pid": 0x4F54,
            "description": "RNode",
            "manufacturer": "",
        }
        score = _rnode_match_score(port_info)
        assert score >= 15

    def test_adafruit_any_pid(self):
        """Adafruit boards (any PID) should score."""
        from talon.platform import _rnode_match_score

        port_info = {
            "vid": 0x239A,
            "pid": 0x1234,
            "description": "Adafruit Feather",
            "manufacturer": "Adafruit",
        }
        score = _rnode_match_score(port_info)
        assert score >= 10

    def test_bluetooth_excluded(self):
        """Bluetooth devices should be excluded."""
        from talon.platform import _rnode_match_score

        port_info = {
            "vid": None,
            "pid": None,
            "description": "Bluetooth Serial Port",
            "manufacturer": "",
        }
        score = _rnode_match_score(port_info)
        assert score == 0

    def test_unknown_device_scores_zero(self):
        """A device with no matching VID or keywords should score 0."""
        from talon.platform import _rnode_match_score

        port_info = {
            "vid": 0x9999,
            "pid": 0x9999,
            "description": "Unknown device",
            "manufacturer": "Unknown",
        }
        score = _rnode_match_score(port_info)
        assert score == 0

    def test_keyword_esp32_scores(self):
        """ESP32 keyword in description should contribute to score."""
        from talon.platform import _rnode_match_score

        port_info = {
            "vid": 0x303A,
            "pid": 0x1001,
            "description": "ESP32-S2",
            "manufacturer": "Espressif",
        }
        score = _rnode_match_score(port_info)
        assert score >= 15

    def test_rnode_usb_ids_is_list(self):
        """RNODE_USB_IDS should be a non-empty list of tuples."""
        from talon.platform import RNODE_USB_IDS

        assert isinstance(RNODE_USB_IDS, list)
        assert len(RNODE_USB_IDS) > 0
        for entry in RNODE_USB_IDS:
            assert isinstance(entry, tuple)
            assert len(entry) == 2


# --- Serial port check ------------------------------------------------------


class TestCheckSerialPort:
    def test_nonexistent_port(self):
        """Checking a nonexistent port should report not exists."""
        from talon.platform import IS_WINDOWS, check_serial_port

        if IS_WINDOWS:
            return  # Windows can't check existence without opening
        result = check_serial_port("/dev/ttyNONEXISTENT999")
        assert result["exists"] is False
        assert result["accessible"] is False
        assert result["error"] is not None

    def test_returns_dict(self):
        """check_serial_port should return a dict with expected keys."""
        from talon.platform import check_serial_port

        result = check_serial_port("/dev/null")
        assert isinstance(result, dict)
        assert "exists" in result
        assert "accessible" in result
        assert "error" in result


# --- RNodeManager -----------------------------------------------------------


class TestRNodeManager:
    def test_initial_status_disconnected(self):
        """Fresh RNodeManager should start as disconnected."""
        from talon.net.rnode import RNodeManager, RNodeStatus

        mgr = RNodeManager()
        assert mgr.status == RNodeStatus.DISCONNECTED
        assert mgr.port is None
        assert mgr.error is None

    def test_with_config(self):
        """RNodeManager should accept config dict."""
        from talon.net.rnode import RNodeManager

        config = {
            "port": "/dev/ttyUSB0",
            "frequency": 915000000,
            "bandwidth": 125000,
            "spreading_factor": 10,
            "coding_rate": 5,
            "tx_power": 17,
        }
        mgr = RNodeManager(config)
        assert mgr.status == "disconnected"

    def test_get_interface_config_when_disconnected(self):
        """Should return empty dict when no RNode is available."""
        from talon.net.rnode import RNodeManager

        mgr = RNodeManager()
        assert mgr.get_interface_config() == {}

    def test_get_status_summary(self):
        """Status summary should always return a dict."""
        from talon.net.rnode import RNodeManager

        mgr = RNodeManager()
        summary = mgr.get_status_summary()
        assert isinstance(summary, dict)
        assert "status" in summary
        assert "port" in summary
        assert "error" in summary

    def test_mark_disconnected(self):
        """mark_disconnected should reset state."""
        from talon.net.rnode import RNodeManager, RNodeStatus

        mgr = RNodeManager()
        mgr._status = RNodeStatus.READY
        mgr._port = "/dev/ttyUSB0"
        mgr.mark_disconnected()
        assert mgr.status == RNodeStatus.DISCONNECTED
        assert mgr.port is None

    def test_mark_in_use(self):
        """mark_in_use should transition from READY to IN_USE."""
        from talon.net.rnode import RNodeManager, RNodeStatus

        mgr = RNodeManager()
        mgr._status = RNodeStatus.READY
        mgr.mark_in_use()
        assert mgr.status == RNodeStatus.IN_USE

    def test_mark_in_use_ignored_if_not_ready(self):
        """mark_in_use should not change status if not READY."""
        from talon.net.rnode import RNodeManager, RNodeStatus

        mgr = RNodeManager()
        mgr._status = RNodeStatus.DISCONNECTED
        mgr.mark_in_use()
        assert mgr.status == RNodeStatus.DISCONNECTED

    def test_validate_without_detect_fails(self):
        """validate should fail if no port has been detected."""
        from talon.net.rnode import RNodeManager

        mgr = RNodeManager()
        assert mgr.validate() is False
        assert mgr.error == "No port detected"

    def test_get_interface_config_with_ready_status(self):
        """Should return full config when status is READY."""
        from talon.net.rnode import RNodeManager, RNodeStatus

        config = {
            "port": "/dev/ttyUSB0",
            "frequency": 868000000,
            "bandwidth": 250000,
            "spreading_factor": 8,
            "coding_rate": 6,
            "tx_power": 20,
        }
        mgr = RNodeManager(config)
        mgr._status = RNodeStatus.READY
        mgr._port = "/dev/ttyUSB0"

        iface = mgr.get_interface_config()
        assert iface["type"] == "RNodeInterface"
        assert iface["port"] == "/dev/ttyUSB0"
        assert iface["frequency"] == 868000000
        assert iface["bandwidth"] == 250000
        assert iface["spreading_factor"] == 8
        assert iface["coding_rate"] == 6
        assert iface["txpower"] == 20

    def test_status_summary_includes_radio_params_when_ready(self):
        """Summary should include radio parameters when READY."""
        from talon.net.rnode import RNodeManager, RNodeStatus

        config = {"frequency": 915000000, "bandwidth": 125000, "spreading_factor": 10, "tx_power": 17}
        mgr = RNodeManager(config)
        mgr._status = RNodeStatus.READY
        mgr._port = "/dev/ttyUSB0"

        summary = mgr.get_status_summary()
        assert summary["frequency_mhz"] == 915.0
        assert summary["bandwidth_khz"] == 125.0
        assert summary["spreading_factor"] == 10
        assert summary["tx_power_dbm"] == 17


# --- RNode status constants -------------------------------------------------


class TestRNodeStatus:
    def test_status_values(self):
        """All status constants should be distinct strings."""
        from talon.net.rnode import RNodeStatus

        statuses = [
            RNodeStatus.DISCONNECTED,
            RNodeStatus.DETECTED,
            RNodeStatus.READY,
            RNodeStatus.ERROR,
            RNodeStatus.IN_USE,
        ]
        assert len(set(statuses)) == 5
        for s in statuses:
            assert isinstance(s, str)


# --- Reticulum config generation --------------------------------------------


class TestReticulumConfigGeneration:
    def test_build_reticulum_config_empty(self):
        """Empty config should produce no interfaces."""
        from talon.net.interfaces import build_reticulum_config

        result = build_reticulum_config({}, is_server=True)
        assert result == {}

    def test_build_reticulum_config_rnode(self):
        """RNode config should produce RNodeInterface."""
        from talon.net.interfaces import build_reticulum_config

        config = {
            "interfaces": {
                "rnode": {
                    "enabled": True,
                    "port": "/dev/ttyUSB0",
                    "frequency": 915000000,
                    "bandwidth": 125000,
                    "spreading_factor": 10,
                    "coding_rate": 5,
                    "tx_power": 17,
                }
            }
        }
        result = build_reticulum_config(config, is_server=True)
        assert "RNode" in result
        assert result["RNode"]["type"] == "RNodeInterface"
        assert result["RNode"]["port"] == "/dev/ttyUSB0"
        assert result["RNode"]["frequency"] == 915000000

    def test_build_reticulum_config_tcp_server(self):
        """TCP server config should produce TCPServerInterface."""
        from talon.net.interfaces import build_reticulum_config

        config = {
            "interfaces": {
                "tcp": {
                    "enabled": True,
                    "listen_port": 4242,
                    "bind_address": "0.0.0.0",
                }
            }
        }
        result = build_reticulum_config(config, is_server=True)
        assert "TCP" in result
        assert result["TCP"]["type"] == "TCPServerInterface"

    def test_build_reticulum_config_tcp_client(self):
        """TCP client config should produce TCPClientInterface."""
        from talon.net.interfaces import build_reticulum_config

        config = {
            "interfaces": {
                "tcp": {
                    "enabled": True,
                    "target_host": "10.0.0.1",
                    "target_port": 4242,
                }
            }
        }
        result = build_reticulum_config(config, is_server=False)
        assert "TCP" in result
        assert result["TCP"]["type"] == "TCPClientInterface"

    def test_build_reticulum_config_disabled_ignored(self):
        """Disabled interfaces should not appear in output."""
        from talon.net.interfaces import build_reticulum_config

        config = {
            "interfaces": {
                "tcp": {"enabled": False},
                "rnode": {"enabled": False},
            }
        }
        result = build_reticulum_config(config, is_server=True)
        assert result == {}

    def test_build_reticulum_config_yggdrasil_server(self):
        """Yggdrasil server should produce TCPServerInterface."""
        from talon.net.interfaces import build_reticulum_config

        config = {
            "interfaces": {
                "yggdrasil": {
                    "enabled": True,
                    "listen_address": "200::1",
                    "listen_port": 4243,
                }
            }
        }
        result = build_reticulum_config(config, is_server=True)
        assert "Yggdrasil" in result
        assert result["Yggdrasil"]["type"] == "TCPServerInterface"

    def test_build_reticulum_config_i2p_client(self):
        """I2P client should produce I2PInterface with peers."""
        from talon.net.interfaces import build_reticulum_config

        config = {
            "interfaces": {
                "i2p": {
                    "enabled": True,
                    "i2p_address": "abc.b32.i2p",
                    "target_port": 4244,
                }
            }
        }
        result = build_reticulum_config(config, is_server=False)
        assert "I2P" in result
        assert result["I2P"]["type"] == "I2PInterface"

    def test_build_reticulum_config_multiple_interfaces(self):
        """Multiple enabled interfaces should all appear."""
        from talon.net.interfaces import build_reticulum_config

        config = {
            "interfaces": {
                "yggdrasil": {"enabled": True, "listen_address": "200::1"},
                "tcp": {"enabled": True, "listen_port": 4242},
                "rnode": {"enabled": True, "port": "/dev/ttyUSB0"},
            }
        }
        result = build_reticulum_config(config, is_server=True)
        assert len(result) == 3
        assert "Yggdrasil" in result
        assert "TCP" in result
        assert "RNode" in result


class TestWriteReticulumConfig:
    def test_write_config_creates_file(self):
        """write_reticulum_config should create a config file."""
        from talon.net.reticulum import write_reticulum_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "reticulum": {"transport_node": True},
                "interfaces": {
                    "tcp": {
                        "enabled": True,
                        "listen_port": 4242,
                        "bind_address": "0.0.0.0",
                    }
                },
            }
            config_dir = write_reticulum_config(config, is_server=True, config_dir=tmpdir)
            config_path = os.path.join(config_dir, "config")
            assert os.path.isfile(config_path)

    def test_config_file_has_interface(self):
        """Generated config should contain the interface definition."""
        from talon.net.reticulum import write_reticulum_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "reticulum": {"transport_node": False},
                "interfaces": {
                    "rnode": {
                        "enabled": True,
                        "port": "/dev/ttyUSB0",
                        "frequency": 915000000,
                    }
                },
            }
            config_dir = write_reticulum_config(config, is_server=True, config_dir=tmpdir)
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

            assert "[[RNode]]" in content
            assert "RNodeInterface" in content
            assert "915000000" in content
            assert "/dev/ttyUSB0" in content

    def test_config_has_transport_setting(self):
        """Generated config should include transport_node setting."""
        from talon.net.reticulum import write_reticulum_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "reticulum": {"transport_node": True},
                "interfaces": {},
            }
            config_dir = write_reticulum_config(config, is_server=True, config_dir=tmpdir)
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

            assert "enable_transport = Yes" in content

    def test_rnode_override(self):
        """RNode override should replace YAML-based RNode config."""
        from talon.net.reticulum import write_reticulum_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "reticulum": {},
                "interfaces": {
                    "rnode": {
                        "enabled": True,
                        "port": "/dev/ttyUSB0",
                        "frequency": 915000000,
                    }
                },
            }
            override = {
                "type": "RNodeInterface",
                "interface_enabled": True,
                "port": "/dev/ttyACM0",
                "frequency": 868000000,
            }
            config_dir = write_reticulum_config(
                config,
                is_server=True,
                config_dir=tmpdir,
                rnode_override=override,
            )
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

            # Should have the override port, not the YAML port
            assert "/dev/ttyACM0" in content
            assert "868000000" in content

    def test_no_interfaces_produces_empty_section(self):
        """Config with no enabled interfaces should still be valid."""
        from talon.net.reticulum import write_reticulum_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"reticulum": {}, "interfaces": {}}
            config_dir = write_reticulum_config(config, is_server=False, config_dir=tmpdir)
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()
            assert "[reticulum]" in content
            assert "[interfaces]" in content


# --- Android USB guards -----------------------------------------------------


class TestAndroidUSBGuards:
    def test_is_android_returns_bool(self):
        """is_android should return a boolean."""
        from talon.net.android_usb import is_android

        result = is_android()
        assert isinstance(result, bool)

    def test_list_usb_devices_on_non_android(self):
        """On non-Android, list_usb_devices should return empty list."""
        from talon.net.android_usb import is_android, list_usb_devices

        if not is_android():
            assert list_usb_devices() == []

    def test_has_usb_permission_on_non_android(self):
        """On non-Android, has_usb_permission should return True."""
        from talon.net.android_usb import has_usb_permission, is_android

        if not is_android():
            assert has_usb_permission() is True

    def test_request_usb_permission_on_non_android(self):
        """On non-Android, request_usb_permission should return True."""
        from talon.net.android_usb import is_android, request_usb_permission

        if not is_android():
            assert request_usb_permission() is True

    def test_find_usb_serial_device_on_non_android(self):
        """On non-Android, find_usb_serial_device should return None."""
        from talon.net.android_usb import find_usb_serial_device, is_android

        if not is_android():
            assert find_usb_serial_device() is None

    def test_get_usb_manager_on_non_android(self):
        """On non-Android, get_usb_manager should return None."""
        from talon.net.android_usb import get_usb_manager, is_android

        if not is_android():
            assert get_usb_manager() is None


# --- Integration: interfaces.py was previously untested ---------------------


class TestInterfacesModule:
    def test_importable(self):
        """interfaces module should be importable."""
        from talon.net.interfaces import build_reticulum_config

        assert callable(build_reticulum_config)

    def test_rnode_same_for_server_and_client(self):
        """RNode config should be identical for server and client."""
        from talon.net.interfaces import build_reticulum_config

        config = {
            "interfaces": {
                "rnode": {
                    "enabled": True,
                    "port": "/dev/ttyUSB0",
                    "frequency": 915000000,
                }
            }
        }
        server = build_reticulum_config(config, is_server=True)
        client = build_reticulum_config(config, is_server=False)
        assert server["RNode"] == client["RNode"]
