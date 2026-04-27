# Legacy Kivy State

Kivy/KivyMD is retired from active TALON desktop work as of 2026-04-27. The
PySide6 desktop is the active Linux release path; do not add Kivy dependencies,
CI jobs, or tests back to active workflows.

## What Remains Useful

- Historical behavior as an acceptance reference when useful.
- Archived source context until the Kivy UI is deleted or moved to a legacy
  branch.

## Known Problems

- SDL/GLX startup can fail with `Couldn't find matching GLX visual`.
- Wayland may be unavailable in the packaged Kivy setup.
- X11/EGL can fail with `Could not get EGL display`.
- Kivy/KivyMD asset collection was fragile under PyInstaller.
- Desktop Documents navigation is missing in the programmatic dashboard.

## Freeze Policy

- Do not build new UI features in Kivy.
- Do not publish Kivy desktop artifacts.
- Do not add Kivy/KivyMD/mapview to active project extras or CI installs.
- Move or delete the archived Kivy UI code in a later cleanup branch when it is
  no longer useful as reference material.
