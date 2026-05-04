"""Static checks for the Windows desktop installer build path."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_SPEC = REPO_ROOT / "build" / "pyinstaller-windows.spec"
INNO_SCRIPT = REPO_ROOT / "build" / "talon-desktop-windows.iss"
RUNTIME_SCRIPT = REPO_ROOT / "build" / "windows" / "talon-runtime.ps1"
DOWNLOAD_SCRIPT = REPO_ROOT / "build" / "windows" / "download-runtime.ps1"
WINDOWS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-talon-desktop-windows.yml"


def test_windows_pyinstaller_spec_uses_pyside_desktop_entrypoint():
    text = WINDOWS_SPEC.read_text(encoding="utf-8")

    assert 'talon_desktop" / "main.py' in text
    assert 'name="talon-desktop"' in text
    assert 'name="talon-desktop-windows"' in text
    assert 'collect_submodules("talon_core")' in text
    assert 'collect_submodules("talon_desktop")' in text
    assert '"kivy"' in text
    assert '"kivymd"' in text
    assert '"mapview"' in text
    assert "talon\" / \"ui\" / \"kv" not in text
    assert 'root / "main.py"' not in text


def test_windows_inno_installer_is_role_aware_and_upgrade_safe():
    text = INNO_SCRIPT.read_text(encoding="utf-8")

    assert '#define ArtifactRole "client"' in text
    assert 'AppId={#AppIdValue}' in text
    assert 'UsePreviousAppDir=yes' in text
    assert "TALONDesktopClient" in text
    assert "TALONDesktopServer" in text
    assert "talon-desktop-{#OutputRole}-windows-setup" in text
    assert "SameRoleDetected" in text
    assert "same-role upgrade detected" in text
    assert "FindSameRoleDataRoot" in text
    assert "LegacyDataRootFor" in text
    assert "OppositeRoleDetected" in text
    assert "Result := False" in text
    assert "Client and server roles must not be overwritten in place" in text
    assert "DeleteDirTree" not in text
    assert "DelTree" not in text


def test_windows_installer_bundles_yggdrasil_and_i2pd():
    inno = INNO_SCRIPT.read_text(encoding="utf-8")
    download = DOWNLOAD_SCRIPT.read_text(encoding="utf-8")
    workflow = WINDOWS_WORKFLOW.read_text(encoding="utf-8")

    assert "dist\\windows-runtime\\installers\\yggdrasil.msi" in inno
    assert "dist\\windows-runtime\\i2pd\\*" in inno
    assert "msiexec.exe" in inno
    assert "ShouldInstallYggdrasil" in inno
    assert "yggdrasil-network/yggdrasil-go" in download
    assert "PurpleI2P/i2pd" in download
    assert "yggdrasil-.*-amd64\\.msi" in download
    assert "i2pd_.*_win64_mingw\\.zip" in download
    assert "download-runtime.ps1" in workflow
    assert "Verify bundled Windows runtimes" in workflow
    assert "innosetup" in workflow


def test_windows_runtime_script_writes_talon_specific_configs():
    text = RUNTIME_SCRIPT.read_text(encoding="utf-8")

    assert "mode = $Role" in text
    assert "rns_config_dir = $RnsDir" in text
    assert "storage_path = $DocumentsDir" in text
    assert "share_instance = No" in text
    assert "TALON AutoInterface" in text
    assert "TALON i2pd $i2pRole" in text
    assert "TALON Yggdrasil Server" in text
    assert "TALON Yggdrasil Client" in text
    assert "[sam]" in text
    assert "address = 127.0.0.1" in text
    assert "port = 7656" in text
    assert "Keeping existing $Path" in text
    assert ".talon-artifact-role" in text
