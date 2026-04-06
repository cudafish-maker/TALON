# build/buildozer.spec
# Buildozer configuration for building the T.A.L.O.N. Android APK.
#
# Buildozer wraps the python-for-android toolchain to compile
# Python + Kivy apps into Android APKs.
#
# To build:
#   python build.py android
#   (or: cd /path/to/talon && buildozer -v android debug)
#
# First build takes a long time (downloads Android SDK/NDK,
# compiles all native dependencies). Subsequent builds are faster.

[app]

# App metadata
title = T.A.L.O.N.
package.name = talon
package.domain = org.talon

# Source code location (relative to project root, where buildozer runs)
source.dir = src
source.include_exts = py,yaml,png,jpg,kv,atlas

# Include config files from project root into the APK
# These are copied alongside the source into the bundle
source.include_patterns = main.py,talon/**/*.py,talon/**/*.kv

# Application version
version = 0.1.0

# Python requirements — Buildozer installs these into the APK.
# Order matters: list base deps first, then packages that depend on them.
# Packages with native code (pynacl, sqlcipher3, argon2-cffi) need
# python-for-android recipes. If a recipe doesn't exist, Buildozer
# will attempt to compile from source using the NDK.
requirements = python3,kivy==2.3.0,kivymd==1.2.0,rns>=1.1.3,lxmf>=0.9.4,pynacl>=1.5.0,argon2-cffi>=23.1.0,pyyaml>=6.0,sqlcipher3>=0.5.0,pyserial>=3.5,mapview>=1.0.6

# Android permissions the app needs
android.permissions = INTERNET,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,ACCESS_NETWORK_STATE,FOREGROUND_SERVICE,WAKE_LOCK,USB_PERMISSION

# Minimum and target Android API levels
# API 24 = Android 7.0 (wide device support)
# API 34 = Android 14 (latest at time of writing)
android.minapi = 24
android.api = 34

# Android NDK version (needed for compiling native extensions)
android.ndk = 25b

# Orientation — landscape is the primary layout for field use
orientation = landscape

# App icon and splash screen (uncomment when assets exist)
# icon.filename = assets/icon.png
# presplash.filename = assets/splash.png

# Keep the screen on while the app is running (field use)
android.wakelock = True

# Allow the app to run as a foreground service (for Reticulum transport)
# The transport service runs Reticulum in the background so the mesh
# stays active even when the app is in the background.
android.services = TalonTransport:talon/service/transport_service.py:foreground

# Whitelist of native libraries to include from p4a recipes
# android.add_libs_armeabi_v7a = libs/android/*.so

# Gradle dependencies for USB serial (RNode OTG access)
android.gradle_dependencies = com.hoho.android.usbserial:usbserial-android:3.7.3

# Accept Android SDK licenses automatically during build
android.accept_sdk_license = True

# Use the latest p4a (python-for-android) distribution
p4a.branch = develop

[buildozer]

# Build log level (0=error, 1=info, 2=debug)
log_level = 2

# Build warnings as errors
warn_on_root = 1
