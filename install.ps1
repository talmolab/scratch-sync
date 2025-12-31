# scratch-sync installer for Windows
# This is a wrapper around SyncthingWindowsSetup by Bill Stewart
# https://github.com/Bill-Stewart/SyncthingWindowsSetup
#
# Direct execution:
#   .\install.ps1              # Install for current user
#   .\install.ps1 -Uninstall   # Uninstall
#   .\install.ps1 -AllUsers    # Install as Windows service (requires admin)
#   .\install.ps1 -Status      # Show dependency status only
#
# Remote execution:
#   iwr -useb https://scratch.tlab.sh/install.ps1 | iex
#   $env:UNINSTALL=1; iwr -useb https://scratch.tlab.sh/install.ps1 | iex
#   $env:ALLUSERS=1; iwr -useb https://scratch.tlab.sh/install.ps1 | iex
#   $env:STATUS=1; iwr -useb https://scratch.tlab.sh/install.ps1 | iex

param(
    [switch]$Uninstall,
    [switch]$AllUsers,
    [switch]$Status
)

# Support environment variables for piped execution (iwr | iex)
# Clear them after reading to prevent persistence across runs
if ($env:UNINSTALL -eq "1") { $Uninstall = $true; $env:UNINSTALL = $null }
if ($env:ALLUSERS -eq "1") { $AllUsers = $true; $env:ALLUSERS = $null }
if ($env:STATUS -eq "1") { $Status = $true; $env:STATUS = $null }

$ErrorActionPreference = "Stop"

# Colors
function Write-Info { Write-Host "info: " -ForegroundColor Blue -NoNewline; Write-Host $args }
function Write-Success { Write-Host "done: " -ForegroundColor Green -NoNewline; Write-Host $args }
function Write-Warning { Write-Host "warn: " -ForegroundColor Yellow -NoNewline; Write-Host $args }
function Write-Err { Write-Host "error: " -ForegroundColor Red -NoNewline; Write-Host $args; exit 1 }

# ============================================================================
# Dependency Status Checks
# ============================================================================

function Check-Uv {
    $uvPath = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
    if ($uvPath) {
        $uvVersion = & uv --version 2>$null | ForEach-Object { ($_ -split ' ')[1] }
        Write-Host "  uv           " -NoNewline
        Write-Host "installed " -ForegroundColor Green -NoNewline
        Write-Host "$uvVersion".PadRight(10) -NoNewline
        Write-Host " $uvPath" -ForegroundColor DarkGray
        return $true
    } else {
        Write-Host "  uv           " -NoNewline
        Write-Host "not found " -ForegroundColor Yellow -NoNewline
        Write-Host " (optional, for 'uvx scratch-sync' CLI)" -ForegroundColor DarkGray
        return $false
    }
}

function Check-Tailscale {
    # Check common Tailscale paths on Windows
    $tsPath = Get-Command tailscale -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
    if (-not $tsPath) {
        $possiblePaths = @(
            "$env:ProgramFiles\Tailscale\tailscale.exe",
            "$env:LOCALAPPDATA\Tailscale\tailscale.exe"
        )
        foreach ($path in $possiblePaths) {
            if (Test-Path $path) {
                $tsPath = $path
                break
            }
        }
    }

    if ($tsPath) {
        $tsVersion = & $tsPath version 2>$null | Select-Object -First 1

        # Check if running and get tailnet info
        $status = & $tsPath status 2>$null
        if ($LASTEXITCODE -eq 0) {
            # Try to get tailnet info from JSON status
            $statusJson = & $tsPath status --json 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue
            $tailnetName = $statusJson.CurrentTailnet.Name
            $userLogin = ""
            if ($statusJson.Self.UserID) {
                $userId = $statusJson.Self.UserID.ToString()
                $userLogin = $statusJson.User.$userId.LoginName
            }

            $details = @()
            if ($tailnetName) { $details += $tailnetName }
            if ($userLogin) { $details += $userLogin }
            $detailsStr = $details -join " / "

            Write-Host "  tailscale    " -NoNewline
            Write-Host "running   " -ForegroundColor Green -NoNewline
            Write-Host "$tsVersion".PadRight(10) -NoNewline
            Write-Host " $detailsStr" -ForegroundColor DarkGray
        } else {
            Write-Host "  tailscale    " -NoNewline
            Write-Host "not running " -ForegroundColor Yellow -NoNewline
            Write-Host "$tsVersion".PadRight(10) -NoNewline
            Write-Host " $tsPath" -ForegroundColor DarkGray
        }
        return $true
    } else {
        Write-Host "  tailscale    " -NoNewline
        Write-Host "not found" -ForegroundColor Red
        Write-Host ""
        Write-Warning "Tailscale is required for device discovery over private network"
        Write-Host "  Install from: https://tailscale.com/download"
        return $false
    }
}

function Check-Syncthing {
    # Find syncthing binary
    $stPath = $null
    if (Test-Path "$InstallDir\syncthing.exe") {
        $stPath = "$InstallDir\syncthing.exe"
    } elseif (Get-Command syncthing -ErrorAction SilentlyContinue) {
        $stPath = Get-Command syncthing | Select-Object -ExpandProperty Source
    }

    if (-not $stPath) {
        Write-Host "  syncthing    " -NoNewline
        Write-Host "not found" -ForegroundColor Red
        return $false
    }

    # Get version
    $stVersion = ""
    $versionOutput = & $stPath --version 2>$null | Select-Object -First 1
    if ($versionOutput -match 'v?([\d\.]+)') {
        $stVersion = "v$($matches[1])"
    }

    # Check if running
    $stProcess = Get-Process syncthing -ErrorAction SilentlyContinue
    if ($stProcess) {
        Write-Host "  syncthing    " -NoNewline
        Write-Host "running   " -ForegroundColor Green -NoNewline
    } else {
        Write-Host "  syncthing    " -NoNewline
        Write-Host "not running " -ForegroundColor Yellow -NoNewline
    }

    # Check autostart (Windows Task Scheduler or Startup folder)
    $autostart = ""
    $task = schtasks /Query /TN "Syncthing" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $autostart = " / autostart: task_scheduler"
    } else {
        $startupPath = [Environment]::GetFolderPath('Startup')
        if (Test-Path "$startupPath\Syncthing.lnk") {
            $autostart = " / autostart: startup_folder"
        }
    }

    Write-Host "$stVersion".PadRight(10) -NoNewline
    Write-Host " $stPath$autostart" -ForegroundColor DarkGray
    return $true
}

function Show-Status {
    Write-Host ""
    Write-Host "Dependencies"
    Write-Host ""
    Check-Uv | Out-Null
    Check-Tailscale | Out-Null
    Check-Syncthing | Out-Null
}

# Installation paths (match SyncthingWindowsSetup defaults)
$InstallDir = if ($AllUsers) { "$env:ProgramFiles\Syncthing" } else { "$env:LOCALAPPDATA\Programs\Syncthing" }
$ConfigDir = if ($AllUsers) { "$env:ProgramData\Syncthing" } else { "$env:LOCALAPPDATA\Syncthing" }

# URLs
$SetupUrl = "https://github.com/Bill-Stewart/SyncthingWindowsSetup/releases/latest/download/syncthing-windows-setup.exe"
$SyncthingReleasesApi = "https://api.github.com/repos/syncthing/syncthing/releases/latest"

function Get-Arch {
    $arch = [Environment]::GetEnvironmentVariable("PROCESSOR_ARCHITECTURE")
    switch ($arch) {
        "AMD64" { return "amd64" }
        "ARM64" { return "arm64" }
        "x86"   { return "386" }
        default { Write-Err "Unsupported architecture: $arch" }
    }
}

function Get-LatestSyncthingVersion {
    try {
        $response = Invoke-RestMethod -Uri $SyncthingReleasesApi -UseBasicParsing
        return $response.tag_name  # e.g., "v1.27.12"
    } catch {
        Write-Err "Failed to get latest Syncthing version: $_"
    }
}

function Install-Syncthing {
    # Check if already installed
    if (Test-Path "$InstallDir\syncthing.exe") {
        $version = & "$InstallDir\syncthing.exe" --version 2>$null | Select-Object -First 1
        if ($version -match 'v([\d\.]+)') {
            Write-Success "Syncthing already installed: $($matches[0])"
            Write-Host ""
            Write-Host "  Location: $InstallDir\syncthing.exe"
            Write-Host "  Config:   $ConfigDir"
            Write-Host "  Web UI:   http://127.0.0.1:8384"
            Write-Host ""
            Write-Info "To reinstall, run: .\install.ps1 -Uninstall; .\install.ps1"
            return
        }
    }

    $tempDir = Join-Path $env:TEMP "scratch-sync-install-$(Get-Random)"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    try {
        # Get latest version
        Write-Info "Checking latest Syncthing version..."
        $version = Get-LatestSyncthingVersion
        $arch = Get-Arch
        Write-Info "Latest version: $version (windows-$arch)"

        # Download Syncthing zip
        $zipUrl = "https://github.com/syncthing/syncthing/releases/download/$version/syncthing-windows-$arch-$version.zip"
        $zipPath = Join-Path $tempDir "syncthing.zip"
        Write-Info "Downloading Syncthing..."
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing

        # Download SyncthingWindowsSetup
        $setupPath = Join-Path $tempDir "syncthing-windows-setup.exe"
        Write-Info "Downloading SyncthingWindowsSetup..."
        Invoke-WebRequest -Uri $SetupUrl -OutFile $setupPath -UseBasicParsing

        # Build arguments for silent install with pre-downloaded zip
        $setupArgs = @("/silent", "/zipfilepath=`"$zipPath`"")

        if ($AllUsers) {
            $setupArgs += "/allusers"
            Write-Info "Installing for all users (Windows service)..."
        } else {
            $setupArgs += "/currentuser"
            Write-Info "Installing for current user..."
        }

        # Run installer (don't use -Wait as it hangs after silent install completes)
        Write-Info "Running SyncthingWindowsSetup (silent)..."
        $process = Start-Process -FilePath $setupPath -ArgumentList $setupArgs -PassThru

        # Wait for the setup process to exit (with timeout)
        $timeout = 120  # seconds
        $waited = 0
        while (-not $process.HasExited -and $waited -lt $timeout) {
            Start-Sleep -Seconds 1
            $waited++
        }

        if (-not $process.HasExited) {
            Write-Warning "Installer is taking longer than expected, but may still complete..."
        } elseif ($process.ExitCode -ne 0) {
            Write-Err "Installation failed with exit code: $($process.ExitCode)"
        }

        # Verify installation succeeded by checking for binary
        Start-Sleep -Seconds 2  # Give it a moment to finish
        if (Test-Path "$InstallDir\syncthing.exe") {
            Write-Success "Installation complete!"
        } else {
            Write-Err "Installation may have failed - syncthing.exe not found"
        }
        Write-Host ""
        Print-Instructions
    }
    finally {
        # Cleanup temp files
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Uninstall-Syncthing {
    # Find uninstaller - check both possible locations
    $possiblePaths = @(
        "$env:LOCALAPPDATA\Programs\Syncthing\uninstall\unins000.exe",
        "$env:ProgramFiles\Syncthing\uninstall\unins000.exe"
    )

    $uninstaller = $null
    foreach ($path in $possiblePaths) {
        if (Test-Path $path) {
            $uninstaller = $path
            break
        }
    }

    if (-not $uninstaller) {
        Write-Err "Syncthing uninstaller not found. Is it installed?"
    }

    Write-Info "Running uninstaller (silent)..."
    $process = Start-Process -FilePath $uninstaller -ArgumentList "/silent" -Wait -PassThru

    if ($process.ExitCode -eq 0) {
        Write-Success "Uninstall complete!"
    } else {
        Write-Warning "Uninstaller exited with code: $($process.ExitCode)"
    }
}

function Print-Instructions {
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host ""
    Write-Success "scratch-sync installation complete!"
    Write-Host ""

    # Show dependency status
    Show-Status

    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Syncthing binary: $InstallDir\syncthing.exe"
    Write-Host "  Config directory: $ConfigDir"
    Write-Host ""

    # Dashboard setup reminder
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Important: " -ForegroundColor Yellow -NoNewline
    Write-Host "Set up a password for the Syncthing dashboard"
    Write-Host ""
    Write-Host "  The dashboard is accessible at:"
    Write-Host "    http://127.0.0.1:8384/" -ForegroundColor Blue
    Write-Host ""
    Write-Host "  On first visit:"
    Write-Host "    1. Go to Actions > Settings > GUI"
    Write-Host "    2. Set a username and password"
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Use Start Menu shortcuts to Start/Stop Syncthing"
    Write-Host ""
    Write-Host "  Get your device ID:"
    Write-Host "    syncthing --device-id"
    Write-Host ""
    Write-Host "  Use the CLI (requires uv or pip):"
    Write-Host "    uvx scratch-sync init     # Initialize in a git repo"
    Write-Host "    uvx scratch-sync pair     # Discover and pair devices"
    Write-Host "    uvx scratch-sync status   # Show sync status"
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
}

# Main
Write-Host ""
Write-Host "scratch-sync installer" -ForegroundColor Cyan
Write-Host "(powered by SyncthingWindowsSetup)" -ForegroundColor DarkGray
Write-Host ""

if ($Status) {
    Show-Status
} elseif ($Uninstall) {
    Uninstall-Syncthing
} else {
    Install-Syncthing
}
