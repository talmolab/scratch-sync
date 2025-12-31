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

# Check if installation is complete (not just binary exists)
function Test-InstallationComplete {
    $result = @{
        HasBinary = Test-Path "$InstallDir\syncthing.exe"
        HasUninstaller = Test-Path "$InstallDir\uninstall\unins000.exe"
        HasStartMenu = Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Syncthing"
        HasAutostart = $false
        Version = $null
    }

    # Check autostart mechanisms
    $task = schtasks /Query /TN "Syncthing" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $result.HasAutostart = $true
    } else {
        $startupPath = [Environment]::GetFolderPath('Startup')
        if (Test-Path "$startupPath\Syncthing.lnk") {
            $result.HasAutostart = $true
        }
    }

    # Get version if binary exists
    if ($result.HasBinary) {
        $versionOutput = & "$InstallDir\syncthing.exe" --version 2>$null | Select-Object -First 1
        if ($versionOutput -match 'v?([\d\.]+)') {
            $result.Version = "v$($matches[1])"
        }
    }

    $result.IsComplete = $result.HasBinary -and $result.HasUninstaller -and $result.HasStartMenu
    return $result
}

function Install-Syncthing {
    # Check if already installed
    $installStatus = Test-InstallationComplete

    if ($installStatus.HasBinary) {
        if ($installStatus.IsComplete) {
            Write-Success "Syncthing already installed: $($installStatus.Version)"
            Write-Host ""
            Write-Host "  Location: $InstallDir\syncthing.exe"
            Write-Host "  Config:   $ConfigDir"
            Write-Host "  Web UI:   http://127.0.0.1:8384"
            Write-Host ""
            Write-Info "To reinstall, run: .\install.ps1 -Uninstall; .\install.ps1"
            return
        } else {
            # Partial installation detected
            Write-Warning "Incomplete Syncthing installation detected:"
            if (-not $installStatus.HasUninstaller) { Write-Host "  - Missing: uninstaller" }
            if (-not $installStatus.HasStartMenu) { Write-Host "  - Missing: Start Menu shortcuts" }
            if (-not $installStatus.HasAutostart) { Write-Host "  - Missing: autostart configuration" }
            Write-Host ""
            Write-Info "Cleaning up and reinstalling..."

            # Stop syncthing if running
            Stop-Process -Name "syncthing" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1

            # Remove partial installation
            Remove-Item -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Syncthing" -Recurse -Force -ErrorAction SilentlyContinue
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

        # Run installer
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
            Write-Warning "Installer is taking longer than expected..."
        } elseif ($process.ExitCode -ne 0) {
            Write-Err "Installation failed with exit code: $($process.ExitCode)"
        }

        # Wait for any child processes (setup may spawn them)
        Write-Info "Waiting for installation to complete..."
        $childWait = 0
        $maxChildWait = 30
        while ($childWait -lt $maxChildWait) {
            $setupProcs = Get-Process -Name "syncthing-windows-setup*" -ErrorAction SilentlyContinue
            if (-not $setupProcs) { break }
            Start-Sleep -Seconds 1
            $childWait++
        }

        # Additional wait for file system operations to complete
        Start-Sleep -Seconds 3

        # Verify installation
        $finalStatus = Test-InstallationComplete

        if (-not $finalStatus.HasBinary) {
            Write-Err "Installation failed - syncthing.exe not found"
        }

        if ($finalStatus.IsComplete) {
            Write-Success "Installation complete!"
        } else {
            Write-Warning "Installation partially complete - some components may be missing:"
            if (-not $finalStatus.HasUninstaller) {
                Write-Host "  - Uninstaller not created (manual removal may be needed)"
            }
            if (-not $finalStatus.HasStartMenu) {
                Write-Host "  - Start Menu shortcuts not created"
            }
            if (-not $finalStatus.HasAutostart) {
                Write-Host "  - Autostart not configured"
                Write-Host ""
                Write-Info "You can start Syncthing manually with:"
                Write-Host "  & `"$InstallDir\syncthing.exe`" --no-browser"
            }
        }

        # Configure GUI binding for remote discovery (required for scratch-sync pair)
        Write-Host ""
        Write-Info "Configuring Syncthing for remote discovery..."

        # Wait for Syncthing to start and create config
        $configWait = 0
        $maxConfigWait = 30
        $configFile = "$ConfigDir\config.xml"
        while (-not (Test-Path $configFile) -and $configWait -lt $maxConfigWait) {
            Start-Sleep -Seconds 1
            $configWait++
        }

        if (Test-Path $configFile) {
            # Check current GUI address
            $currentAddress = & "$InstallDir\syncthing.exe" cli config gui raw-address get 2>$null
            if ($currentAddress -match "^127\.0\.0\.1" -or $currentAddress -match "^localhost") {
                # Change to 0.0.0.0 for remote discovery
                & "$InstallDir\syncthing.exe" cli config gui raw-address set "0.0.0.0:8384" 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-Success "GUI binding set to 0.0.0.0:8384 for remote discovery"

                    # Restart Syncthing to apply the change
                    $stProcess = Get-Process syncthing -ErrorAction SilentlyContinue
                    if ($stProcess) {
                        Write-Info "Restarting Syncthing to apply changes..."
                        & "$InstallDir\syncthing.exe" cli operations restart 2>$null
                        Start-Sleep -Seconds 2
                    }
                } else {
                    Write-Warning "Could not configure GUI binding automatically"
                    Write-Host "  Run manually: & `"$InstallDir\syncthing.exe`" cli config gui raw-address set 0.0.0.0:8384"
                }
            } else {
                Write-Host "  GUI already configured for remote access: $currentAddress" -ForegroundColor DarkGray
            }
        } else {
            Write-Warning "Syncthing config not found yet - GUI binding not configured"
            Write-Host "  Run after first start: & `"$InstallDir\syncthing.exe`" cli config gui raw-address set 0.0.0.0:8384"
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
    # Check current installation status
    $installStatus = Test-InstallationComplete

    if (-not $installStatus.HasBinary -and -not $installStatus.HasUninstaller -and -not $installStatus.HasStartMenu) {
        Write-Err "Syncthing does not appear to be installed."
    }

    # Stop syncthing if running
    $stProcess = Get-Process -Name "syncthing" -ErrorAction SilentlyContinue
    if ($stProcess) {
        Write-Info "Stopping Syncthing..."
        Stop-Process -Name "syncthing" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    # Try official uninstaller first
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

    if ($uninstaller) {
        Write-Info "Running uninstaller (silent)..."
        $process = Start-Process -FilePath $uninstaller -ArgumentList "/silent" -Wait -PassThru

        if ($process.ExitCode -eq 0) {
            Write-Success "Uninstall complete!"
        } else {
            Write-Warning "Uninstaller exited with code: $($process.ExitCode)"
        }
    } else {
        # No uninstaller - perform manual cleanup
        Write-Warning "No uninstaller found - performing manual cleanup..."

        # Remove install directory
        $dirsToRemove = @(
            "$env:LOCALAPPDATA\Programs\Syncthing",
            "$env:ProgramFiles\Syncthing"
        )
        foreach ($dir in $dirsToRemove) {
            if (Test-Path $dir) {
                Write-Info "Removing $dir..."
                Remove-Item -Path $dir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }

        # Remove Start Menu shortcuts
        $startMenuPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Syncthing"
        if (Test-Path $startMenuPath) {
            Write-Info "Removing Start Menu shortcuts..."
            Remove-Item -Path $startMenuPath -Recurse -Force -ErrorAction SilentlyContinue
        }

        # Remove Startup shortcut if exists
        $startupPath = [Environment]::GetFolderPath('Startup')
        $startupShortcut = "$startupPath\Syncthing.lnk"
        if (Test-Path $startupShortcut) {
            Write-Info "Removing startup shortcut..."
            Remove-Item -Path $startupShortcut -Force -ErrorAction SilentlyContinue
        }

        # Try to remove scheduled task if exists
        $taskExists = schtasks /Query /TN "Syncthing" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Info "Removing scheduled task..."
            schtasks /Delete /TN "Syncthing" /F 2>$null
        }

        Write-Success "Manual cleanup complete!"
        Write-Host ""
        Write-Info "Note: Configuration data was preserved at:"
        Write-Host "  $env:LOCALAPPDATA\Syncthing"
        Write-Host ""
        Write-Host "  To remove config data, run:"
        Write-Host "  Remove-Item -Path `"$env:LOCALAPPDATA\Syncthing`" -Recurse -Force"
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
