param(
    [ValidateSet("client", "server")]
    [string]$Role,
    [string]$InstallRoot = "",
    [string]$DataRoot = "",
    [switch]$Initialize,
    [switch]$Start,
    [switch]$Stop,
    [string]$Launch = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $InstallRoot) {
    $InstallRoot = Split-Path -Parent $PSScriptRoot
}
if (-not $DataRoot) {
    $DataRoot = Join-Path $env:LOCALAPPDATA "TALON\desktop-$Role"
}

$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$ConfigPath = Join-Path $DataRoot "talon.ini"
$RnsDir = Join-Path $DataRoot "reticulum"
$DocumentsDir = Join-Path $DataRoot "documents"
$I2pdDir = Join-Path $DataRoot "i2pd"
$I2pdConfig = Join-Path $I2pdDir "i2pd.conf"
$YggdrasilDir = Join-Path $DataRoot "yggdrasil"
$YggdrasilConfig = Join-Path $YggdrasilDir "yggdrasil.conf"

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Write-IfMissing {
    param(
        [string]$Path,
        [string]$Content
    )

    if (Test-Path -LiteralPath $Path) {
        Write-Host "Keeping existing $Path"
        return
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    Write-Utf8NoBom -Path $Path -Content $Content
    Write-Host "Created $Path"
}

function Get-YggdrasilExe {
    $candidates = @(
        (Join-Path $InstallRoot "runtime\yggdrasil\yggdrasil.exe"),
        (Join-Path $env:ProgramFiles "Yggdrasil\yggdrasil.exe")
    )
    if (${env:ProgramFiles(x86)}) {
        $candidates += Join-Path ${env:ProgramFiles(x86)} "Yggdrasil\yggdrasil.exe"
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return ""
}

function Get-I2pdExe {
    $candidate = Join-Path $InstallRoot "runtime\i2pd\i2pd.exe"
    if (Test-Path -LiteralPath $candidate) {
        return $candidate
    }

    $found = Get-ChildItem -Path (Join-Path $InstallRoot "runtime\i2pd") `
        -Filter "i2pd.exe" `
        -Recurse `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) {
        return $found.FullName
    }

    throw "Bundled i2pd.exe was not found under $InstallRoot\runtime\i2pd"
}

function New-TalonConfigText {
    @"
[talon]
mode = $Role

[paths]
data_dir = $DataRoot
rns_config_dir = $RnsDir

[network]
transport_priority = yggdrasil,i2p,tcp,rnode

[security]
lease_duration_seconds = 86400

[documents]
storage_path = $DocumentsDir
"@
}

function New-ReticulumConfigText {
    $enableTransport = "False"
    if ($Role -eq "server") {
        $enableTransport = "True"
    }

    $i2pRole = "Client"
    $i2pEnabled = "No"
    $i2pConnectable = "No"
    $i2pComment = "    # Set peers to the server .b32.i2p address, then enable this stanza."
    if ($Role -eq "server") {
        $i2pRole = "Server"
        $i2pEnabled = "Yes"
        $i2pConnectable = "Yes"
        $i2pComment = ""
    }

    @"
[reticulum]
  enable_transport = $enableTransport
  share_instance = No

[logging]
  loglevel = 4

[interfaces]
  [[TALON AutoInterface]]
    type = AutoInterface
    enabled = Yes

  [[TALON i2pd $i2pRole]]
    type = I2PInterface
    enabled = $i2pEnabled
    connectable = $i2pConnectable
$i2pComment

  [[TALON Yggdrasil Server]]
    type = TCPServerInterface
    enabled = No
    listen_ip = ::
    listen_port = 4343

  [[TALON Yggdrasil Client]]
    type = TCPClientInterface
    enabled = No
    # Set target_host to the server Yggdrasil IPv6 address, then enable this stanza.
    target_host = 200::
    target_port = 4343

# TCP, Yggdrasil, I2P, and RNode interfaces are deployment-specific.
# The Windows installer bundles Yggdrasil and i2pd, but server addresses and
# peer lists still need to match the deployment.
"@
}

function New-I2pdConfigText {
    @"
# TALON-bundled i2pd configuration.
ipv4 = true
ipv6 = true
log = file
logfile = $($I2pdDir)\i2pd.log

[http]
enabled = true
address = 127.0.0.1
port = 7070

[sam]
enabled = true
address = 127.0.0.1
port = 7656
"@
}

function Initialize-YggdrasilConfig {
    New-Item -ItemType Directory -Force -Path $YggdrasilDir | Out-Null
    if (Test-Path -LiteralPath $YggdrasilConfig) {
        Write-Host "Keeping existing $YggdrasilConfig"
        return
    }

    $yggdrasilExe = Get-YggdrasilExe
    if ($yggdrasilExe) {
        $configText = (& $yggdrasilExe -genconf) -join [Environment]::NewLine
        Write-Utf8NoBom -Path $YggdrasilConfig -Content ($configText + [Environment]::NewLine)
        Write-Host "Created $YggdrasilConfig"
    } else {
        Write-Host "Yggdrasil executable was not found yet; the MSI may finish service setup after reboot."
    }
}

function Initialize-TalonRuntime {
    New-Item -ItemType Directory -Force -Path `
        $DataRoot, `
        $RnsDir, `
        $DocumentsDir, `
        $I2pdDir, `
        $YggdrasilDir | Out-Null

    Write-IfMissing -Path $ConfigPath -Content (New-TalonConfigText)
    Write-IfMissing -Path (Join-Path $RnsDir "config") -Content (New-ReticulumConfigText)
    Write-IfMissing -Path $I2pdConfig -Content (New-I2pdConfigText)
    Initialize-YggdrasilConfig
    Write-IfMissing -Path (Join-Path $DataRoot ".talon-artifact-role") -Content "$Role`r`n"
}

function Find-I2pdProcess {
    Get-CimInstance Win32_Process -Filter "Name = 'i2pd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($I2pdConfig) } |
        Select-Object -First 1
}

function Start-I2pd {
    $existing = Find-I2pdProcess
    if ($existing) {
        Write-Host "i2pd is already running for $I2pdConfig"
        return
    }

    $i2pdExe = Get-I2pdExe
    New-Item -ItemType Directory -Force -Path $I2pdDir | Out-Null
    Start-Process `
        -FilePath $i2pdExe `
        -ArgumentList @("--conf=$I2pdConfig", "--datadir=$I2pdDir") `
        -WindowStyle Hidden `
        -WorkingDirectory (Split-Path -Parent $i2pdExe)
    Write-Host "Started bundled i2pd."
}

function Start-Yggdrasil {
    $service = Get-Service -Name "yggdrasil" -ErrorAction SilentlyContinue
    if (-not $service) {
        $service = Get-Service -Name "Yggdrasil" -ErrorAction SilentlyContinue
    }
    if (-not $service) {
        Write-Host "Yggdrasil service was not found. The bundled MSI may require a reboot or manual repair."
        return
    }
    if ($service.Status -ne "Running") {
        try {
            Start-Service -InputObject $service
            Write-Host "Started Yggdrasil service."
        } catch {
            Write-Host "Could not start Yggdrasil service: $($_.Exception.Message)"
        }
    }
}

function Start-TalonRuntime {
    Initialize-TalonRuntime
    Start-Yggdrasil
    Start-I2pd
}

function Stop-I2pd {
    $existing = Find-I2pdProcess
    if ($existing) {
        Stop-Process -Id $existing.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped bundled i2pd."
    }
}

if ($Launch) {
    Start-TalonRuntime
} else {
    if ($Start) {
        Start-TalonRuntime
    } elseif ($Initialize) {
        Initialize-TalonRuntime
    }
    if ($Stop) {
        Stop-I2pd
    }
}
if ($Launch) {
    $env:TALON_CONFIG = $ConfigPath
    Start-Process `
        -FilePath $Launch `
        -ArgumentList @("--config", "`"$ConfigPath`"") `
        -WorkingDirectory (Split-Path -Parent $Launch)
}
