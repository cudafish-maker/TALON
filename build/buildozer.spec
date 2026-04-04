# build/buildozer.spec
# Buildozer configuration for building the T.A.L.O.N. Android APK.
#
# Buildozer wraps the python-for-android toolchain to compile
# Python + Kivy apps into Android APKs.
#
# To build:
#   cd /path/to/talon
#   buildozer -v android debug
#
# First build takes a long time (downloads Android SDK/NDK,
# compiles all native dependencies). Subsequent builds are faster.

[app]

# App metadata
title = T.A.L.O.N.
package.name = talon
package.domain = org.talon

# Source code location (relative to this file)
source.dir = ../src
source.include_exts = py,yaml,png,jpg,kv,atlas

# Application version
version = 0.1.0

# Python requirements — Buildozer installs these into the APK
# NOTE: Some packages need recipes (custom build instructions for Android).
# Kivy and most of its deps have recipes already. SQLCipher and
# PyNaCl may need custom recipes depending on the Buildozer version.
requirements = python3,kivy==2.3.1,kivymd==1.2.0,mapview==1.0.6,rns==1.1.4,lxmf==0.9.4,pynacl==1.6.2,argon2-cffi==25.1.0,pyyaml,sqlcipher3==0.6.2

# Android permissions the app needs
android.permissions = INTERNET,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,ACCESS_NETWORK_STATE,FOREGROUND_SERVICE,WAKE_LOCK

# Minimum and target Android API levels
# API 24 = Android 7.0 (wide device support)
# API 34 = Android 14 (latest at time of writing)
android.minapi = 24
android.api = 34

# Android NDK version (needed for compiling native extensions)
android.ndk = 25b

# Orientation — horizontal (landscape) is the primary layout
# Users will hold the phone sideways
orientation = landscape

# App icon and splash screen (paths relative to this file)
# icon.filename = ../assets/icon.png
# presplash.filename = ../assets/splash.png

# Kivy entry point
# Buildozer looks for a main.py in source.dir by default.
# We'll create a thin wrapper that imports and starts the client app.
# entrypoint = main.py

# Keep the screen on while the app is running (field use)
android.wakelock = True

# Allow the app to run as a foreground service (for Reticulum transport)
android.services = TalonTransport:talon/service/transport_service.py:foreground

[buildozer]

# Build log level (0=error, 1=info, 2=debug)
log_level = 2

# Build warnings as errors
warn_on_root = 1
