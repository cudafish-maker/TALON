# Legacy Kivy State

Kivy/KivyMD is the current implementation but no longer the target desktop or
mobile architecture.

## What Remains Useful

- Existing workflows and behavior.
- Existing tests around core-like behavior.
- Current screen behavior as acceptance reference.
- Emergency release patches if a Kivy build must ship before PySide6 parity.

## Known Problems

- SDL/GLX startup can fail with `Couldn't find matching GLX visual`.
- Wayland may be unavailable in the packaged Kivy setup.
- X11/EGL can fail with `Could not get EGL display`.
- Kivy/KivyMD asset collection was fragile under PyInstaller.
- Desktop Documents navigation is missing in the programmatic dashboard.

## Freeze Policy

- Do not build new strategic UI features in Kivy.
- Patch only emergency release blockers or migration helpers.
- Retire Kivy release artifacts after PySide6 desktop reaches feature parity.
