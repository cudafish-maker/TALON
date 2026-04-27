# Linux Release Readiness

_Last reviewed: 2026-04-26 by Codex._

Purpose: track the remaining work and release decisions before shipping the Linux server and client builds.

## Current Assessment

- Linux server: close to ship-ready from source; release packaging now has an in-tree gate, but the packaged startup path still needs final GitHub Actions validation after the latest KivyMD/Kivy/PyInstaller fixes.
- Linux client: synced document open/download now works over the persistent sync link with a local encrypted cache when the Documents screen is reached; release readiness depends on GitHub Actions packaged startup validation, restoring visible desktop navigation to Documents (BUG-085), plus acceptance of the remaining document-scope limitations.
- Linux installer: `build/install-talon.sh` is now packaged into the release tarball as `talon-linux/install.sh`. Users extract `talon-linux.tar.gz`, `cd talon-linux`, and run `bash ./install.sh --mode client --yes`; the installer uses its own extracted bundle directory as the source and no longer scans nearby archives or accepts archive inputs. It checks/installs runtime dependencies including GLX/Mesa DRI packages needed by Kivy/OpenGL, finds `ldconfig` under `/sbin`/`/usr/sbin` and falls back to common library paths for normal-user dependency checks, validates the bundled Kivy data and KivyMD icon definitions, creates config/data/RNS/document directories, writes a launcher wrapper, and can run an optional packaged smoke test. `main.py` and the installed launcher pin Kivy to the SDL2 window provider, default to Mesa software GL, and disable desktop Kivy multisampling before window creation to avoid `No matching FB config found` on GLX stacks that cannot allocate the default framebuffer. The installed launcher now streams all startup attempts to a state-dir log, retries known SDL/Kivy GLX visual/framebuffer startup failures through a `glxinfo`-detected X11 visual ID, retries X11 with SDL visual auto-selection override, tries Wayland only if the bundled Kivy setup reports Wayland support, and finally retries X11/EGL; EGL is still not the first default path after Linux Mint returned `Could not get EGL display`.
- Latest local validation: `pytest -q` passed with `199 passed in 613.84s` on 2026-04-25.
- Latest local packaged smoke: after rebuilding `dist/talon-linux/`, `TALON_CONFIG=build/talon-smoke-client.ini TALON_SMOKE_TEST_SECONDS=2 timeout 30s dist/talon-linux/talon` reached `TalonApp started`, scheduled the smoke shutdown, and exited with code 0 on 2026-04-25.
- Latest targeted installer validation: `bash -n build/install-talon.sh` and `pytest -q tests/test_linux_installer.py` passed on 2026-04-26, covering the installed launcher's retry from the observed `Couldn't find matching GLX visual` failure through detected X11 visual ID and eventual `SDL_VIDEO_X11_FORCE_EGL=1` fallbacks.
- Local sandbox note: the exact CI command with `xvfb-run` could not be trusted locally because even `xvfb-run -a true` returns code 1 in the Codex sandbox due `/tmp/.X11-unix` ownership (`nobody:nogroup`). GitHub-hosted Ubuntu should not have that local sandbox condition.

## Release Blockers

- [x] Resolve Linux client document behavior.
  Implemented: clients now send `document_request` over the persistent sync link, the server returns plaintext over `RNS.Resource`, and the client stores a local encrypted cache entry so subsequent opens can work offline.
  Cache coherence: client-side cache entries are evicted automatically when synced document metadata changes (`sha256_hash` mismatch/version bump) or the document row is deleted.
  Remaining limitation: client upload is still intentionally blocked, and the first client-side open still requires an active broadband sync link.

- [~] Validate the Linux PyInstaller release gate in CI.
  Current state: `.github/workflows/build-desktop.yml` now installs the hashed KivyMD GitHub archive, adds Linux runtime packages (`libmagic1`, `xvfb`, `xauth`), runs `pytest -q`, builds the Linux PyInstaller artifact under Xvfb with `--clean --noconfirm`, verifies the packaged runtime assets (`base_library.zip`, `kivy/data/style.kv`, `kivymd/icon_definitions.py`), smoke-starts `dist/talon-linux/talon` under Xvfb with `build/talon-smoke-client.ini`, copies the installer into `dist/talon-linux/install.sh`, packages the tarball, extracts that tarball under a deliberately versioned/space-containing filename, and smoke-installs from the extracted `talon-linux/` directory. On tag pushes it publishes `talon-linux.tar.gz` and `talon-linux.tar.gz.sha256` as GitHub Release assets.
  Latest blocker found by the new smoke path: the packaged app first failed because `kivymd.icon_definitions` and Kivy data assets were missing, then failed because the temporary `kivymd.icon_definitions.md_icons` runtime shim made KivyMD receive a module instead of the `md_icons` dictionary.
  In-tree fixes: `build/pyinstaller-linux.spec` now explicitly includes `kivymd/icon_definitions.py`, explicitly adds the Kivy `data/` tree, and no longer loads the KivyMD `md_icons` runtime shim. `build/pyinstaller-windows.spec` now mirrors the same Kivy/KivyMD collection settings for the Windows desktop matrix.
  Remaining: trigger a clean GitHub Actions rerun and observe a green Linux build plus smoke run before release sign-off.

- [ ] Restore visible desktop navigation to the Documents screen.
  Current state: `DocumentScreen` is registered and document fetch/cache is implemented, but the programmatic desktop dashboard exposes quick-nav controls only for mission, SITREP, and chat. BUG-085 tracks adding a visible Documents control or restoring a shared navigation surface that includes `documents`.

- [x] Make the Linux dependency/install path reproducible.
  Desktop CI now installs KivyMD from the exact tested GitHub archive hash before `pip install -e ".[dev,desktop]"`.
  The Linux workflow also installs the runtime packages needed by the packaged app and document pipeline (`libmagic`, SQLCipher runtime/development package in CI, OpenGL/X11 helpers, clipboard support). The installer dependency set now includes GLX/Mesa DRI packages, and the app plus launcher pin Kivy to SDL2, default to Mesa software GL, and disable Kivy desktop multisampling, to address fresh-machine Kivy startup failures such as `No matching FB config found`.
  The Linux release artifact is now packaged as `talon-linux.tar.gz` plus a separate SHA-256 checksum asset. The installer is embedded at the top of the extracted bundle as `talon-linux/install.sh`; users install from the extracted directory, so the installer no longer needs archive auto-discovery and cannot pick unrelated downloads. It validates required PyInstaller/Kivy assets (`base_library.zip`, `kivy/data/style.kv`, `kivymd/icon_definitions.py`), creates TALON config/data/RNS/document directories, and writes a `talon` launcher that pins `TALON_CONFIG`, `KIVY_HOME`, and the Kivy/SDL graphics environment defaults. The launcher preserves startup output in `$XDG_STATE_HOME/talon/launcher.log` (or `~/.local/state/talon/launcher.log`) and retries the known SDL/Kivy GLX visual/framebuffer failures through Wayland and X11/EGL before surfacing diagnostic commands.

## Release Decisions Needed

- [ ] Confirm whether the following deferred items are acceptable for the first Linux release:
  DM E2E encryption remains deferred to Phase 2b.
  Group key rotation remains a stub in the server keys screen.
  AO tile pre-cache remains deferred.
  Large-file broadband-only document handling remains pending.
  Client document upload remains server-only; client download requires an active broadband sync link for the first fetch and then reuses the local encrypted cache. Desktop Documents navigation must be restored before relying on this flow in release testing.

## Recommended Minimum Exit Criteria

- [ ] Linux server and client both pass `pytest -q` in the release workflow.
- [ ] Linux PyInstaller build completes in CI, required runtime assets are present in the bundle, and the packaged app is smoke-tested.
- [x] Linux client document open/download behavior is implemented for the first release scope via persistent-link fetch plus local encrypted cache.
- [ ] Desktop UI exposes a reachable Documents entry for server upload/delete and client open/download flows.
- [x] Linux installer is embedded in the extracted release bundle, validates bundled Kivy/KivyMD assets, creates local config/storage paths, and generates a launcher wrapper.
- [ ] Release notes call out all accepted deferred items and known limitations.

## Relevant Files

- `talon/ui/screens/document_screen.py`
- `talon/documents.py`
- `talon/network/registry.py`
- `talon/app.py`
- `build/pyinstaller-linux.spec`
- `build/pyinstaller-windows.spec`
- `build/install-talon.sh`
- `build/talon-smoke-client.ini`
- `.github/workflows/build-desktop.yml`
- `pyproject.toml`
