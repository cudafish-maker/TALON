# Desktop Packaging

Desktop packaging target is Linux first, then Windows. The current priority is
a polished Linux server/client release candidate before Windows work starts.

## Target Direction

- PySide6 Linux package replaces the Kivy/SDL release path.
- Windows packaging follows after the Linux server/client release candidate is
  accepted.
- Desktop imports `talon-core` directly.
- `pip install -e ".[desktop]"` installs the PySide6 desktop path without
  resolving legacy Kivy/KivyMD. Kivy now lives under the `legacy-kivy` extra.

## Current Legacy Kivy State

The current Linux package is PyInstaller-based and includes Kivy/KivyMD runtime
assets. Recent work added:

- `talon-linux.tar.gz` artifact plus SHA-256 checksum.
- Embedded installer at `talon-linux/install.sh`.
- Runtime dependency checks for GLX/Mesa DRI pieces.
- Kivy data and KivyMD icon definitions bundled directly.
- Launcher startup logs under the TALON state dir.
- SDL/GLX fallback attempts for known visual/framebuffer failures.

The launcher still failed on a user machine after GLX, Wayland, and EGL
fallbacks. This reinforces the move to PySide6.

## Current Dependency Split

- Base dependencies are shared core/runtime packages: Reticulum, crypto,
  SQLCipher binding, and document security packages.
- `desktop` adds PySide6 and PyInstaller only.
- `legacy-kivy` contains Kivy, the KivyMD Git dependency, and mapview for the
  temporary compatibility client.

## PySide6 Linux Package Path

The PySide6 package path is separate from the legacy Kivy package path:

- PyInstaller spec: `build/pyinstaller-linux-desktop.spec`
- Installer script embedded as `install.sh`: `build/install-talon-desktop.sh`
- Manual workflow: `.github/workflows/build-talon-desktop-linux.yml`
- Bundle directory: `dist/talon-desktop-linux/`
- Client release tarball: `dist/talon-desktop-client-linux.tar.gz`
- Server release tarball: `dist/talon-desktop-server-linux.tar.gz`
- SHA-256 files: matching `.sha256` files for both role-specific tarballs.

The package entry point is `talon-desktop`, not legacy `talon`. The package
smoke command is:

```bash
QT_QPA_PLATFORM=offscreen dist/talon-desktop-linux/talon-desktop --smoke --mode server
QT_QPA_PLATFORM=offscreen dist/talon-desktop-linux/talon-desktop --smoke --mode client
```

The workflow stamps the shared PyInstaller output into role-specific bundles
with `.talon-artifact-role` set to `client` or `server`. The installer reads
that marker and rejects `--mode`; role selection comes from the artifact, not
operator input.

Client install:

```bash
tar -xzf talon-desktop-client-linux.tar.gz
cd talon-desktop-client-linux
./install.sh --yes
```

Server install:

```bash
tar -xzf talon-desktop-server-linux.tar.gz
cd talon-desktop-server-linux
./install.sh --yes
```

For test installs that should not modify desktop launchers:

```bash
./install.sh --no-deps --no-bin --no-desktop --smoke-test \
  --prefix /tmp/talon-desktop-install \
  --config /tmp/talon-desktop-config/talon.ini \
  --data-dir /tmp/talon-desktop-data
```

Client artifacts create `talon-desktop-client` and
`talon-desktop-client.desktop`. Server artifacts create `talon-desktop-server`
and `talon-desktop-server.desktop`. The installer does not create a generic
`talon-desktop` launcher.

Client and server installs cannot coexist for one local user. If the installer
detects an existing opposite-role or legacy TALON footprint, it stops and warns
that all previous local TALON files, databases, RNS identities, documents,
bundles, launchers, desktop entries, and logs will be deleted. `--yes` does not
authorize this. The operator must type `DELETE TALON DATA`, or controlled
automation/tests must pass `--confirm-delete "DELETE TALON DATA"`.

Server installs should be treated as dedicated or hardened operator machines
because server profiles contain higher-value local authority and identity
material.

As of 2026-04-26, a local PyInstaller build produced an 86 MB
`talon-desktop-linux.tar.gz` artifact. The packaged executable smoke passed in
server and client modes, and an extracted tarball install smoke passed in a
temporary install root.

As of 2026-04-27, manual target Linux Mint validation confirmed that the package
installs and launches without the old Kivy/SDL/GLX startup failure. The packaged
artifact and an extracted installed package also passed `talon-desktop
--loopback-smoke`, which covers server startup, token generation, client
enrollment, and server-to-client asset sync over Reticulum TCP loopback.

Current caveat: the PySide6 bundles do not contain Kivy/KivyMD or SDL assets,
but Qt still bundles optional XCB GLX integration files.

## Linux Release Polish

Before Windows packaging starts, the Linux PySide6 path needs a server/client
release candidate pass:

- durable desktop settings for window geometry and operator UI choices;
- global desktop error reporting or log-view affordance;
- manual server and client acceptance from the packaged artifact;
- paired enrollment and sync acceptance on target Linux systems;
- install, reinstall or upgrade, launcher, role-switch deletion, and removal
  notes;
- release notes with deferred items, limitations, and troubleshooting.

## Acceptance

- Linux PySide6 package installs and launches on the target Linux Mint
  environment.
- Server and client modes run from the package.
- Linux server/client release candidate is accepted after release polish.
- Windows package is validated after the accepted Linux release.
- Release notes call out deferred items and known limitations.

## Legacy Source

Distilled from
[../archive/legacy/linux_release_readiness.md](../archive/legacy/linux_release_readiness.md).
