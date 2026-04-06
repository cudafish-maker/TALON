# talon/platform.py
# Platform detection and path resolution.
#
# T.A.L.O.N. runs on Linux, Windows, and Android. Each platform has
# different conventions for data directories, serial ports, and file
# viewers. This module detects the platform once at import time and
# provides helpers so the rest of the codebase doesn't need to care.

import os
import sys
import platform as _platform


# --- Platform detection -----------------------------------------------------

def _detect():
    """Detect the current platform.

    Returns one of: "linux", "windows", "android", "macos", "unknown".
    """
    # Android check first — it reports as Linux but has ANDROID_ROOT
    if hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ:
        return "android"
    system = _platform.system().lower()
    if system == "linux":
        return "linux"
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return "unknown"


PLATFORM = _detect()
IS_ANDROID = PLATFORM == "android"
IS_WINDOWS = PLATFORM == "windows"
IS_LINUX = PLATFORM == "linux"
IS_MACOS = PLATFORM == "macos"


# --- Data directories -------------------------------------------------------

def get_data_dir(app_name: str = "talon") -> str:
    """Get the platform-appropriate data directory.

    Creates the directory if it doesn't exist.

    Linux:   ~/.local/share/talon/
    Windows: %LOCALAPPDATA%/talon/
    macOS:   ~/Library/Application Support/talon/
    Android: /data/data/org.talon.talon/files/ (or external storage)

    Args:
        app_name: Subdirectory name (default "talon").

    Returns:
        Absolute path to the data directory.
    """
    if IS_ANDROID:
        # Android — use app-private internal storage
        try:
            from android.storage import app_storage_path  # type: ignore
            base = app_storage_path()
        except ImportError:
            base = os.environ.get(
                "ANDROID_PRIVATE", "/data/data/org.talon.talon/files"
            )
        path = os.path.join(base, app_name)
    elif IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        path = os.path.join(base, app_name)
    elif IS_MACOS:
        path = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", app_name
        )
    else:
        # Linux / XDG
        base = os.environ.get(
            "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
        )
        path = os.path.join(base, app_name)

    os.makedirs(path, exist_ok=True)
    return path


def get_config_dir(app_name: str = "talon") -> str:
    """Get the platform-appropriate config directory.

    Linux:   ~/.config/talon/
    Windows: %LOCALAPPDATA%/talon/config/
    macOS:   ~/Library/Application Support/talon/config/
    Android: same as data dir

    Args:
        app_name: Subdirectory name (default "talon").

    Returns:
        Absolute path to the config directory.
    """
    if IS_ANDROID:
        return get_data_dir(app_name)
    elif IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        path = os.path.join(base, app_name, "config")
    elif IS_MACOS:
        path = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support",
            app_name, "config"
        )
    else:
        base = os.environ.get(
            "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")
        )
        path = os.path.join(base, app_name)

    os.makedirs(path, exist_ok=True)
    return path


# --- Bundled resource resolution --------------------------------------------

def get_bundled_path(relative_path: str) -> str:
    """Resolve a path relative to the app bundle.

    Works correctly whether running from source, pip install, or a
    PyInstaller/Buildozer bundle.

    Args:
        relative_path: Path relative to the package root
                       (e.g. "config/default.yaml").

    Returns:
        Absolute path to the resource.
    """
    # PyInstaller sets _MEIPASS to the temp extraction directory
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)

    # Installed package — relative to the talon package directory
    package_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up from src/talon/ to the project root
    project_root = os.path.join(package_dir, "..", "..")
    candidate = os.path.normpath(os.path.join(project_root, relative_path))
    if os.path.exists(candidate):
        return candidate

    # Fallback: relative to cwd
    return os.path.abspath(relative_path)


# --- Serial port enumeration ------------------------------------------------

def list_serial_ports() -> list:
    """List all available serial ports on this machine.

    Uses pyserial's port enumeration. Each entry is a dict with:
      - port: device path (e.g. "/dev/ttyUSB0", "COM3")
      - description: human-readable description
      - hwid: hardware ID string (USB VID:PID etc.)

    Returns:
        List of dicts, sorted by port name. Empty list if pyserial
        is not installed or no ports are found.
    """
    try:
        from serial.tools.list_ports import comports
        ports = []
        for info in sorted(comports(), key=lambda p: p.device):
            ports.append({
                "port": info.device,
                "description": info.description or "",
                "hwid": info.hwid or "",
                "vid": info.vid,
                "pid": info.pid,
                "serial_number": info.serial_number or "",
                "manufacturer": info.manufacturer or "",
            })
        return ports
    except ImportError:
        return []
    except Exception:
        return []


# Known USB VID:PID pairs for RNode-compatible hardware.
# RNode devices are typically based on ESP32 with CP2102/CH340/FTDI chips.
RNODE_USB_IDS = [
    (0x10C4, 0xEA60),  # Silicon Labs CP2102/CP2104 (most common RNode)
    (0x1A86, 0x7523),  # QinHeng CH340
    (0x0403, 0x6001),  # FTDI FT232R
    (0x0403, 0x6010),  # FTDI FT2232
    (0x0403, 0x6015),  # FTDI FT-X series
    (0x303A, 0x1001),  # Espressif ESP32-S2 native USB
    (0x303A, 0x80D1),  # Espressif ESP32-S3 native USB
    (0x239A, None),     # Adafruit boards (any PID)
    (0x1209, 0x4F54),   # unsigned.io RNode (official VID:PID)
]


def detect_rnode_ports() -> list:
    """Detect serial ports that are likely RNode hardware.

    Checks each available serial port against known USB vendor/product
    IDs used by RNode-compatible devices. Also matches by description
    keywords as a fallback.

    Returns:
        List of port dicts (same format as list_serial_ports) that
        are likely RNode devices, best candidates first.
    """
    all_ports = list_serial_ports()
    if not all_ports:
        return []

    candidates = []
    for port_info in all_ports:
        score = _rnode_match_score(port_info)
        if score > 0:
            candidates.append((score, port_info))

    # Sort by score descending (best match first)
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [info for _, info in candidates]


def _rnode_match_score(port_info: dict) -> int:
    """Score how likely a serial port is an RNode device.

    Returns:
        0 = no match, higher = better match.
    """
    score = 0
    vid = port_info.get("vid")
    pid = port_info.get("pid")

    if vid is not None:
        for known_vid, known_pid in RNODE_USB_IDS:
            if vid == known_vid:
                if known_pid is None or pid == known_pid:
                    score += 10
                    if known_pid is not None:
                        score += 5  # Exact PID match is stronger
                    break

    # Keyword matching in description and hwid
    desc = (port_info.get("description", "") + " " +
            port_info.get("manufacturer", "")).lower()
    for keyword in ("rnode", "lora", "esp32", "cp210", "ch340", "ftdi"):
        if keyword in desc:
            score += 3

    # Penalize ports that are clearly not RNode
    for exclude in ("bluetooth", "modem", "built-in", "internal"):
        if exclude in desc:
            score -= 20

    return max(score, 0)


def get_default_serial_port() -> str:
    """Get the default serial port for RNode LoRa hardware.

    Tries to auto-detect an RNode first. Falls back to a
    platform-appropriate default.

    Returns:
        Serial device path string.
    """
    # Try auto-detection first
    rnode_ports = detect_rnode_ports()
    if rnode_ports:
        return rnode_ports[0]["port"]

    # Platform defaults
    if IS_WINDOWS:
        return "COM3"
    if IS_ANDROID:
        return "/dev/ttyUSB0"
    # Linux / macOS
    return "/dev/ttyUSB0"


def check_serial_port(port: str) -> dict:
    """Check if a serial port exists and is accessible.

    Args:
        port: Device path (e.g. "/dev/ttyUSB0", "COM3").

    Returns:
        Dict with keys:
          - exists: True if the port device exists
          - accessible: True if we can open it
          - error: Error message if not accessible, else None
    """
    result = {"exists": False, "accessible": False, "error": None}

    if IS_WINDOWS:
        # On Windows, we can't easily check existence without opening
        result["exists"] = True  # Assume exists, check via open
    else:
        result["exists"] = os.path.exists(port)
        if not result["exists"]:
            result["error"] = f"Device {port} does not exist"
            return result

    try:
        import serial
        ser = serial.Serial(port, baudrate=115200, timeout=1)
        ser.close()
        result["accessible"] = True
    except ImportError:
        result["error"] = "pyserial not installed"
    except PermissionError:
        result["exists"] = True
        result["error"] = (
            f"Permission denied on {port}. "
            "Add your user to the 'dialout' group: "
            "sudo usermod -aG dialout $USER"
        )
    except Exception as exc:
        result["error"] = str(exc)

    return result


# --- File viewer -------------------------------------------------------------

def open_file(path: str) -> bool:
    """Open a file with the platform's default viewer.

    Args:
        path: Absolute path to the file.

    Returns:
        True if the viewer was launched.
    """
    if not path or not os.path.isfile(path):
        return False

    try:
        if IS_WINDOWS:
            os.startfile(path)
        elif IS_ANDROID:
            # Android — use Intent via pyjnius
            try:
                from jnius import autoclass  # type: ignore
                Intent = autoclass("android.content.Intent")
                Uri = autoclass("android.net.Uri")
                File = autoclass("java.io.File")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")

                intent = Intent(Intent.ACTION_VIEW)
                uri = Uri.fromFile(File(path))
                intent.setDataAndType(uri, "*/*")
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                PythonActivity.mActivity.startActivity(intent)
            except ImportError:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        elif IS_MACOS:
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False
