# TALON Desktop Install and Setup

This guide covers the current Linux PySide6 desktop packages. Install either
the client package or the server package for a local user, not both.

## Choose A Package

- Client: `talon-desktop-client-linux.tar.gz`
- Server: `talon-desktop-server-linux.tar.gz`

If a matching `.sha256` file is provided, verify the download first:

```bash
sha256sum -c talon-desktop-client-linux.tar.gz.sha256
sha256sum -c talon-desktop-server-linux.tar.gz.sha256
```

## Install

Client:

```bash
tar -xzf talon-desktop-client-linux.tar.gz
cd talon-desktop-client-linux
bash ./install.sh --yes
```

Client with a known server I2P peer:

```bash
bash ./install.sh --yes --i2p-peer SERVER_ADDRESS.b32.i2p
```
This can also be configured from within Talon, and is how I recommend doing it.

Server:

```bash
tar -xzf talon-desktop-server-linux.tar.gz
cd talon-desktop-server-linux
bash ./install.sh --yes
```

The installer creates role-specific launchers:

- Client: `talon-desktop-client`
- Server: `talon-desktop-server`

Desktop menu entries are also created when desktop launcher installation is
enabled.

## First Launch

1. Launch TALON with the role-specific launcher.
2. Create or enter the local database passphrase.
3. Review and accept the TALON Reticulum configuration after unlock.
4. Server operators should create enrollment tokens from the server admin UI.
5. Client operators should enter the server-provided enrollment token and server
   hash, then wait for server approval and sync.

The installer creates a TALON-specific Reticulum config by default. Add any
deployment-specific TCP, Yggdrasil, I2P, or RNode interface settings before
depending on those transports in the field.

## Default Paths

- Install root: `$XDG_DATA_HOME/talon` or `~/.local/share/talon`
- Launchers: `~/.local/bin`
- Client data: `~/.talon`
- Server data: `~/.talon-server`
- Config: `<data-dir>/talon.ini`
- Reticulum config and identity: `<data-dir>/reticulum`
- Documents: `<data-dir>/documents`

## Role Switches And Uninstall

Client and server installs cannot safely coexist for the same local user. A
role switch deletes local TALON data, databases, documents, launchers, and
Reticulum identity material only after this exact confirmation phrase:

```text
DELETE TALON DATA
```

To uninstall from an extracted package directory:

```bash
bash ./install.sh --uninstall --confirm-delete "DELETE TALON DATA"
```

Uninstall removes local TALON files for the selected install paths. It does not
remove system packages such as `i2pd`.
