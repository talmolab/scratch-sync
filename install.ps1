# scratch-sync installer for Windows
# Usage: iwr -useb https://scratch.tlab.sh/install.ps1 | iex
#
# Or download and run:
#   Invoke-WebRequest -Uri https://scratch.tlab.sh/install.ps1 -OutFile install.ps1
#   .\install.ps1

param(
    [string]$SyncthingVersion = "2.0.12",
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\syncthing",
    [switch]$NoService,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

# Colors
function Write-Info { Write-Host "info: " -ForegroundColor Blue -NoNewline; Write-Host $args }
function Write-Success { Write-Host "done: " -ForegroundColor Green -NoNewline; Write-Host $args }
function Write-Warning { Write-Host "warn: " -ForegroundColor Yellow -NoNewline; Write-Host $args }
function Write-Err { Write-Host "error: " -ForegroundColor Red -NoNewline; Write-Host $args; exit 1 }

# Detect architecture
function Get-Arch {
    $arch = [Environment]::GetEnvironmentVariable("PROCESSOR_ARCHITECTURE")
    switch ($arch) {
        "AMD64" { return "amd64" }
        "ARM64" { return "arm64" }
        "x86"   { return "386" }
        default { Write-Err "Unsupported architecture: $arch" }
    }
}

# Check if syncthing already exists
function Test-ExistingInstall {
    if (Test-Path "$InstallDir\syncthing.exe") {
        $version = & "$InstallDir\syncthing.exe" --version 2>$null | Select-Object -First 1
        Write-Warning "Syncthing already installed at: $InstallDir"
        Write-Warning "Version: $version"

        $reply = Read-Host "Continue with installation? [y/N]"
        if ($reply -notmatch '^[yY]') {
            Write-Info "Installation cancelled"
            exit 0
        }
    }

    # Check if running
    $proc = Get-Process -Name "syncthing" -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Warning "Syncthing is currently running"
        Write-Info "Stopping syncthing..."
        Stop-Process -Name "syncthing" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}

# Install syncthing
function Install-Syncthing {
    Write-Info "Installing Syncthing v$SyncthingVersion..."

    $arch = Get-Arch
    Write-Info "Detected architecture: windows-$arch"

    # Create install directory
    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }

    # Download URL
    $downloadUrl = "https://github.com/syncthing/syncthing/releases/download/v$SyncthingVersion/syncthing-windows-$arch-v$SyncthingVersion.zip"
    Write-Info "Downloading from: $downloadUrl"

    # Create temp directory
    $tempDir = Join-Path $env:TEMP "syncthing-install-$(Get-Random)"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    try {
        # Download
        $zipPath = Join-Path $tempDir "syncthing.zip"
        Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing

        # Extract
        Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force

        # Find binary
        $binary = Get-ChildItem -Path $tempDir -Recurse -Filter "syncthing.exe" | Select-Object -First 1
        if (-not $binary) {
            Write-Err "Could not find syncthing.exe in downloaded archive"
        }

        # Copy to install dir
        Copy-Item -Path $binary.FullName -Destination "$InstallDir\syncthing.exe" -Force

        Write-Success "Installed syncthing to $InstallDir\syncthing.exe"

        # Verify
        $version = & "$InstallDir\syncthing.exe" --version 2>$null | Select-Object -First 1
        Write-Success "Verified: $version"
    }
    finally {
        # Cleanup
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# Add to PATH
function Add-ToPath {
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -notlike "*$InstallDir*") {
        Write-Warning "$InstallDir is not in your PATH"
        $reply = Read-Host "Add to PATH? [y/N]"
        if ($reply -match '^[yY]') {
            [Environment]::SetEnvironmentVariable("Path", "$currentPath;$InstallDir", "User")
            Write-Success "Added $InstallDir to user PATH"
            Write-Info "Restart your terminal for PATH changes to take effect"
        }
    }
}

# Setup auto-start via Task Scheduler
function Setup-Service {
    if ($NoService) {
        Write-Info "Skipping service setup (-NoService specified)"
        return
    }

    $taskName = "Syncthing"

    # Check if task exists
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        Write-Warning "Scheduled task '$taskName' already exists"
        $reply = Read-Host "Replace it? [y/N]"
        if ($reply -match '^[yY]') {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        } else {
            return
        }
    }

    # Create task
    $action = New-ScheduledTaskAction -Execute "$InstallDir\syncthing.exe" -Argument "--no-browser"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null

    # Start it now
    Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

    Write-Success "Created scheduled task '$taskName'"
    Write-Info "Syncthing will start automatically on login"
}

# Uninstall
function Uninstall-Syncthing {
    Write-Info "Uninstalling scratch-sync/syncthing..."

    # Stop process
    Stop-Process -Name "syncthing" -Force -ErrorAction SilentlyContinue

    # Remove scheduled task
    $task = Get-ScheduledTask -TaskName "Syncthing" -ErrorAction SilentlyContinue
    if ($task) {
        Unregister-ScheduledTask -TaskName "Syncthing" -Confirm:$false
        Write-Success "Removed scheduled task"
    }

    # Remove binary
    if (Test-Path "$InstallDir\syncthing.exe") {
        Remove-Item -Path "$InstallDir\syncthing.exe" -Force
        Write-Success "Removed $InstallDir\syncthing.exe"
    }

    # Ask about config
    $configDir = "$env:LOCALAPPDATA\Syncthing"
    if (Test-Path $configDir) {
        Write-Warning "Config directory exists: $configDir"
        $reply = Read-Host "Remove config and data? This cannot be undone! [y/N]"
        if ($reply -match '^[yY]') {
            Remove-Item -Path $configDir -Recurse -Force
            Write-Success "Removed config directory"
        } else {
            Write-Info "Config preserved at: $configDir"
        }
    }

    # Remove from PATH
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -like "*$InstallDir*") {
        $newPath = ($currentPath -split ';' | Where-Object { $_ -ne $InstallDir }) -join ';'
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Success "Removed $InstallDir from PATH"
    }

    Write-Success "Uninstall complete"
}

# Print instructions
function Print-Instructions {
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host ""
    Write-Success "scratch-sync installation complete!"
    Write-Host ""
    Write-Host "  Syncthing binary: $InstallDir\syncthing.exe"
    Write-Host "  Config directory: $env:LOCALAPPDATA\Syncthing"
    Write-Host "  Web UI: http://127.0.0.1:8384"
    Write-Host ""
    Write-Host "  Get your device ID:"
    Write-Host "    syncthing --device-id"
    Write-Host ""
    Write-Host "  View status:"
    Write-Host "    syncthing cli show system"
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
}

# Main
function Main {
    Write-Host ""
    Write-Host "scratch-sync installer" -ForegroundColor Cyan
    Write-Host ""

    if ($Uninstall) {
        Uninstall-Syncthing
        return
    }

    Test-ExistingInstall
    Install-Syncthing
    Add-ToPath
    Setup-Service
    Print-Instructions
}

Main
