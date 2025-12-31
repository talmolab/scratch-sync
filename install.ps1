# scratch-sync installer for Windows
# Usage: iwr -useb https://scratch.tlab.sh/install.ps1 | iex
#
# This is a wrapper around SyncthingWindowsSetup by Bill Stewart
# https://github.com/Bill-Stewart/SyncthingWindowsSetup
#
# Options:
#   -Uninstall    Uninstall syncthing
#   -AllUsers     Install as Windows service (requires admin)

param(
    [switch]$Uninstall,
    [switch]$AllUsers
)

$ErrorActionPreference = "Stop"

# Colors
function Write-Info { Write-Host "info: " -ForegroundColor Blue -NoNewline; Write-Host $args }
function Write-Success { Write-Host "done: " -ForegroundColor Green -NoNewline; Write-Host $args }
function Write-Warning { Write-Host "warn: " -ForegroundColor Yellow -NoNewline; Write-Host $args }
function Write-Err { Write-Host "error: " -ForegroundColor Red -NoNewline; Write-Host $args; exit 1 }

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
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Syncthing binary: $InstallDir\syncthing.exe"
    Write-Host "  Config directory: $ConfigDir"
    Write-Host "  Web UI: http://127.0.0.1:8384"
    Write-Host ""
    Write-Host "  Use Start Menu shortcuts to Start/Stop Syncthing"
    Write-Host ""
    Write-Host "  Get your device ID:"
    Write-Host "    syncthing --device-id"
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
}

# Main
Write-Host ""
Write-Host "scratch-sync installer" -ForegroundColor Cyan
Write-Host "(powered by SyncthingWindowsSetup)" -ForegroundColor DarkGray
Write-Host ""

if ($Uninstall) {
    Uninstall-Syncthing
} else {
    Install-Syncthing
}
