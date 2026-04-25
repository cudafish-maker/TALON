# Linux Release Readiness

_Last reviewed: 2026-04-25 by Codex._

Purpose: track the remaining work and release decisions before shipping the Linux server and client builds.

## Current Assessment

- Linux server: close to ship-ready from source; release packaging still needs a proper gate.
- Linux client: not ship-ready until the document workflow is either completed or explicitly removed from release scope.
- Latest local validation: `KIVY_HOME=/tmp/.kivy PYTHONPATH=. pytest -q` passed with `195 passed in 107.41s` on 2026-04-25.

## Release Blockers

- [ ] Resolve Linux client document behavior.
  Current state: client upload is intentionally blocked in `talon/ui/screens/document_screen.py`.
  Blocking issue: synced `documents` rows redact `file_path`, but client download still calls `download_document()` and expects a local encrypted blob on disk.
  Impact: Linux clients can list document records but cannot reliably open synced documents.
  Release options: implement client-side document blob sync/cache, or hide/remove client document access from the Linux release and document the limitation.

- [ ] Add a release gate for the Linux PyInstaller artifact.
  Current state: `.github/workflows/build-desktop.yml` installs dependencies, runs PyInstaller, and uploads artifacts.
  Missing: automated `pytest` in the desktop build workflow and a smoke test that the packaged Linux binary starts cleanly.

- [ ] Make the Linux dependency/install path reproducible.
  `pyproject.toml` says KivyMD 2.x must come from GitHub, but CI currently installs with `pip install -e ".[desktop]"`.
  The Linux workflow also installs `libsqlcipher-dev`, `libgl1-mesa-dev`, and `xclip`, but not `libmagic1`, even though the document pipeline expects it for full MIME detection.

## Release Decisions Needed

- [ ] Confirm whether the following deferred items are acceptable for the first Linux release:
  DM E2E encryption remains deferred to Phase 2b.
  Group key rotation remains a stub in the server keys screen.
  AO tile pre-cache remains deferred.
  Large-file broadband-only document handling remains pending.

## Recommended Minimum Exit Criteria

- [ ] Linux server and client both pass `pytest -q` in the release workflow.
- [ ] Linux PyInstaller build completes in CI and the packaged app is smoke-tested.
- [ ] Document behavior on Linux client is either fully implemented or explicitly removed from scope.
- [ ] Release notes call out all accepted deferred items and known limitations.

## Relevant Files

- `talon/ui/screens/document_screen.py`
- `talon/documents.py`
- `talon/network/registry.py`
- `build/pyinstaller-linux.spec`
- `.github/workflows/build-desktop.yml`
- `pyproject.toml`
