#!/usr/bin/env python3
# main.py — Android entry point for Buildozer.
#
# Buildozer expects a main.py in the source directory. This thin
# wrapper imports and launches the Kivy client app. On Android, the
# talon package is bundled inside the APK by Buildozer.
#
# This file is ONLY used for Android builds. Desktop builds use
# talon-client.py (PyInstaller) or talon.client.cli (pip install).

import os
import sys

# On Android, set up platform-appropriate data directory BEFORE
# importing anything that might touch the filesystem.
if hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ:
    # Use Android internal storage for all data
    try:
        from android.storage import app_storage_path  # type: ignore
        data_dir = app_storage_path()
    except ImportError:
        data_dir = os.environ.get(
            "ANDROID_PRIVATE", "/data/data/org.talon.talon/files"
        )
    os.makedirs(os.path.join(data_dir, "talon"), exist_ok=True)
    os.environ.setdefault("TALON_DATA_DIR", os.path.join(data_dir, "talon"))

from talon.ui.app import run_client  # noqa: E402

if __name__ == "__main__":
    run_client()
