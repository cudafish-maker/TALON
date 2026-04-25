[app]
title = TALON
package.name = talon
package.domain = net.talon
source.dir = ..
source.include_exts = py,kv,ini
source.exclude_patterns = talon/server/*,talon/ui/screens/server/*

version = 0.1.0
requirements = python3,kivy==2.3.1,kivymd,rns,pynacl,argon2-cffi,sqlcipher3
# Phase 4 notes:
#   - Add 'pillow' here when document image re-encoding is needed on Android.
#   - Do NOT add 'python-magic': libmagic has no p4a recipe and is unavailable
#     on Android. documents.py handles ImportError gracefully (extension-only
#     MIME check). Upload security runs server-side anyway.

orientation = landscape
fullscreen = 0

# Android
android.api = 34
android.minapi = 26
android.ndk = 25b
android.archs = arm64-v8a
android.allow_backup = False

# Permissions
android.permissions = INTERNET,ACCESS_NETWORK_STATE

[buildozer]
log_level = 2
warn_on_root = 1
