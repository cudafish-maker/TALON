# talon/net/android_usb.py
# Android USB OTG permission handling for RNode serial access.
#
# On Android, USB serial devices (like RNode) require explicit
# permission from the user before the app can open them. This
# module handles the permission request flow using pyjnius to
# call the Android USB Manager API.
#
# This module is only imported on Android — it's a no-op import
# guard on other platforms.

import logging
import os
import sys

log = logging.getLogger(__name__)


def is_android() -> bool:
    """Check if we're running on Android."""
    return hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ


def get_usb_manager():
    """Get the Android UsbManager service.

    Returns:
        The UsbManager instance, or None if not on Android.
    """
    if not is_android():
        return None

    try:
        from jnius import autoclass  # type: ignore

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        activity = PythonActivity.mActivity
        return activity.getSystemService(Context.USB_SERVICE)
    except Exception as exc:
        log.warning("Could not get USB manager: %s", exc)
        return None


def list_usb_devices() -> list:
    """List all connected USB devices on Android.

    Returns:
        List of dicts with vendor_id, product_id, device_name.
        Empty list on non-Android platforms or if no devices found.
    """
    if not is_android():
        return []

    try:
        usb_manager = get_usb_manager()
        if usb_manager is None:
            return []

        device_list = usb_manager.getDeviceList()
        devices = []
        for name in device_list.keySet().toArray():
            device = device_list.get(name)
            devices.append(
                {
                    "device_name": device.getDeviceName(),
                    "vendor_id": device.getVendorId(),
                    "product_id": device.getProductId(),
                    "manufacturer": _safe_get_manufacturer(device),
                }
            )
        return devices
    except Exception as exc:
        log.warning("Could not list USB devices: %s", exc)
        return []


def _safe_get_manufacturer(device) -> str:
    """Safely get manufacturer name from USB device."""
    try:
        name = device.getManufacturerName()
        return name if name else ""
    except Exception:
        return ""


def has_usb_permission(device_name: str = None) -> bool:
    """Check if we have permission to access a USB device.

    Args:
        device_name: The Android device path (e.g., "/dev/bus/usb/001/002").
                     If None, checks the first available device.

    Returns:
        True if permission is granted.
    """
    if not is_android():
        return True  # Non-Android platforms don't need USB permission

    try:
        usb_manager = get_usb_manager()
        if usb_manager is None:
            return False

        device_list = usb_manager.getDeviceList()
        if device_name:
            device = device_list.get(device_name)
        else:
            # Check first device
            keys = device_list.keySet().toArray()
            if not keys:
                return False
            device = device_list.get(keys[0])

        if device is None:
            return False

        return usb_manager.hasPermission(device)
    except Exception as exc:
        log.warning("Could not check USB permission: %s", exc)
        return False


def request_usb_permission(device_name: str = None, callback=None) -> bool:
    """Request USB permission from the user via Android dialog.

    This triggers the system USB permission dialog. The result is
    delivered asynchronously via a BroadcastReceiver.

    Args:
        device_name: The Android device path. If None, requests
                     for the first available USB device.
        callback: Optional function(granted: bool) called when
                  the user responds to the permission dialog.

    Returns:
        True if the permission request was sent (not granted yet).
        False if request could not be sent.
    """
    if not is_android():
        return True

    try:
        from jnius import autoclass  # type: ignore

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        PendingIntent = autoclass("android.app.PendingIntent")
        Intent = autoclass("android.content.Intent")

        activity = PythonActivity.mActivity
        usb_manager = activity.getSystemService(Context.USB_SERVICE)
        device_list = usb_manager.getDeviceList()

        if device_name:
            device = device_list.get(device_name)
        else:
            keys = device_list.keySet().toArray()
            if not keys:
                log.warning("No USB devices found for permission request")
                return False
            device = device_list.get(keys[0])

        if device is None:
            log.warning("USB device not found: %s", device_name)
            return False

        # Already have permission
        if usb_manager.hasPermission(device):
            log.info("USB permission already granted for %s", device.getDeviceName())
            if callback:
                callback(True)
            return True

        # Request permission — Android shows a system dialog
        ACTION_USB_PERMISSION = "org.talon.USB_PERMISSION"
        intent = Intent(ACTION_USB_PERMISSION)
        pending = PendingIntent.getBroadcast(activity, 0, intent, PendingIntent.FLAG_IMMUTABLE)
        usb_manager.requestPermission(device, pending)
        log.info("USB permission requested for %s", device.getDeviceName())
        return True
    except Exception as exc:
        log.warning("Could not request USB permission: %s", exc)
        return False


def find_usb_serial_device() -> dict:
    """Find a USB serial device suitable for RNode on Android.

    Searches connected USB devices for known RNode VID:PID pairs.

    Returns:
        Dict with device_name, vendor_id, product_id, or None.
    """
    if not is_android():
        return None

    from talon.platform import RNODE_USB_IDS

    devices = list_usb_devices()
    for dev in devices:
        vid = dev.get("vendor_id")
        pid = dev.get("product_id")
        for known_vid, known_pid in RNODE_USB_IDS:
            if vid == known_vid:
                if known_pid is None or pid == known_pid:
                    return dev
    return None
