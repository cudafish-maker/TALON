# TALON Desktop Install and Setup

This guide covers the current PySide6 desktop packages. Install either the
client package or the server package for a local user, not both.

## Choose A Package

- Client: `talon-desktop-client-linux.tar.gz`
- Server: `talon-desktop-server-linux.tar.gz`
- Windows client: `talon-desktop-client-windows-setup.exe`
- Windows server: `talon-desktop-server-windows-setup.exe`

If a matching `.sha256` file is provided, verify the download first:

```bash
sha256sum -c talon-desktop-client-linux.tar.gz.sha256
sha256sum -c talon-desktop-server-linux.tar.gz.sha256
```

On Windows, use PowerShell:

```powershell
Get-FileHash .\talon-desktop-client-windows-setup.exe -Algorithm SHA256
Get-FileHash .\talon-desktop-server-windows-setup.exe -Algorithm SHA256
```

## Linux Install

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

## Windows Install

Run the role-specific setup executable:

```powershell
.\talon-desktop-client-windows-setup.exe
.\talon-desktop-server-windows-setup.exe
```

The Windows setup executable is built for a clean machine. It installs the
frozen TALON desktop app, bundles i2pd, bundles the official Yggdrasil Windows
MSI, creates a TALON-specific config, and creates a TALON-specific Reticulum
config. The Start Menu shortcut starts TALON through the installed runtime
helper so bundled i2pd is started before the app opens.

Run a newer setup executable for the same role to update TALON in place. Same
role upgrades preserve the local database, documents, Reticulum identity
material, i2pd config, Yggdrasil config, and `talon.ini`. If the installer finds
the opposite role, it stops instead of overwriting that role's local data.

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

Linux:

- Install root: `$XDG_DATA_HOME/talon` or `~/.local/share/talon`
- Launchers: `~/.local/bin`
- Client data: `~/.talon`
- Server data: `~/.talon-server`
- Config: `<data-dir>/talon.ini`
- Reticulum config and identity: `<data-dir>/reticulum`
- Documents: `<data-dir>/documents`

Windows:

- Install root: `C:\Program Files\TALON\Desktop Client` or
  `C:\Program Files\TALON\Desktop Server`
- Client data: `%LOCALAPPDATA%\TALON\desktop-client`
- Server data: `%LOCALAPPDATA%\TALON\desktop-server`
- Legacy same-role data is preserved if found at `%USERPROFILE%\.talon` or
  `%USERPROFILE%\.talon-server`
- Config: `<data-dir>\talon.ini`
- Reticulum config and identity: `<data-dir>\reticulum`
- Documents: `<data-dir>\documents`
- Bundled i2pd config: `<data-dir>\i2pd\i2pd.conf`
- Yggdrasil config: `<data-dir>\yggdrasil\yggdrasil.conf` when the Yggdrasil
  executable is available during setup

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

Windows uninstall removes the installed TALON application files. It intentionally
preserves local TALON data so a later same-role installer can update or restore
the existing profile. Remove the role data directory manually only after the
database, documents, and Reticulum identities are no longer needed.
