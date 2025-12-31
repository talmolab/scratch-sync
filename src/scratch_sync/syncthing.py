"""Syncthing CLI and API interactions."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_syncthing() -> str | None:
    """Find syncthing binary in common locations."""
    # Check PATH first (cross-platform)
    binary = shutil.which("syncthing")
    if binary:
        return binary

    # Platform-specific common paths
    if sys.platform == "win32":
        common_paths = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Syncthing" / "syncthing.exe",
            Path("C:/Program Files/Syncthing/syncthing.exe"),
        ]
    else:
        common_paths = [
            Path.home() / ".local" / "bin" / "syncthing",
            Path("/usr/local/bin/syncthing"),
            Path("/opt/homebrew/bin/syncthing"),
        ]

    # Check common paths
    for path in common_paths:
        if path.exists():
            return str(path)

    return None


def run_syncthing_cli(*args: str) -> subprocess.CompletedProcess:
    """Run a syncthing CLI command."""
    binary = find_syncthing()
    if not binary:
        print("Error: syncthing not found. Run the installer first.", file=sys.stderr)
        sys.exit(1)

    return subprocess.run([binary, "cli", *args], capture_output=True, text=True)


def get_device_id() -> str:
    """Get the local device ID."""
    binary = find_syncthing()
    if not binary:
        raise RuntimeError("Syncthing not installed")

    # Syncthing 2.0+ uses subcommand, older uses flag
    result = subprocess.run([binary, "device-id"], capture_output=True, text=True)
    if result.returncode != 0:
        # Try old flag format
        result = subprocess.run([binary, "--device-id"], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get device ID: {result.stderr}")

    return result.stdout.strip()


def get_system_info() -> dict:
    """Get system info from syncthing."""
    result = run_syncthing_cli("show", "system")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get system info: {result.stderr}")

    return json.loads(result.stdout)


def list_folders() -> list[str]:
    """List all configured folder IDs."""
    result = run_syncthing_cli("config", "folders", "list")
    if result.returncode != 0:
        return []

    return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]


def list_devices() -> list[str]:
    """List all configured device IDs."""
    result = run_syncthing_cli("config", "devices", "list")
    if result.returncode != 0:
        return []

    return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]


def folder_exists(folder_id: str) -> bool:
    """Check if a folder exists in the config."""
    return folder_id in list_folders()


def add_folder(folder_id: str, path: Path) -> bool:
    """Add a folder to Syncthing."""
    result = run_syncthing_cli(
        "config", "folders", "add",
        "--id", folder_id,
        "--path", str(path),
    )
    if result.returncode != 0:
        print(f"Error adding folder: {result.stderr}", file=sys.stderr)
        return False

    # Set folder type to send-receive
    run_syncthing_cli("config", "folders", folder_id, "type", "set", "sendreceive")

    return True


def add_device(device_id: str, name: str | None = None) -> bool:
    """Add a device to Syncthing."""
    args = ["config", "devices", "add", "--device-id", device_id]
    if name:
        args.extend(["--name", name])

    result = run_syncthing_cli(*args)
    return result.returncode == 0


def set_device_address(device_id: str, address: str) -> bool:
    """Set the address for a device (e.g., tcp://100.x.y.z:22000)."""
    result = run_syncthing_cli(
        "config", "devices", device_id, "addresses", "set", address
    )
    return result.returncode == 0


def add_device_to_folder(folder_id: str, device_id: str) -> bool:
    """Add a device to a folder's sharing list."""
    result = run_syncthing_cli(
        "config", "folders", folder_id, "devices", "add",
        "--device-id", device_id
    )
    return result.returncode == 0


def get_folder_status(folder_id: str) -> dict | None:
    """Get the status of a folder."""
    return api_get(f"/rest/db/status?folder={folder_id}")


def get_connections() -> dict:
    """Get connection status for all devices."""
    result = run_syncthing_cli("show", "connections")
    if result.returncode != 0:
        return {}

    return json.loads(result.stdout)


def get_gui_address() -> str | None:
    """Get current GUI listen address."""
    result = run_syncthing_cli("config", "gui", "raw-address", "get")
    return result.stdout.strip() if result.returncode == 0 else None


def set_gui_address(address: str) -> bool:
    """Set GUI listen address (requires Syncthing restart to take effect)."""
    result = run_syncthing_cli("config", "gui", "raw-address", "set", address)
    return result.returncode == 0


def is_gui_localhost_only() -> bool:
    """Check if GUI is bound to localhost only."""
    address = get_gui_address()
    if not address:
        return True
    host = address.split(":")[0] if ":" in address else address
    return host in ("127.0.0.1", "localhost", "::1")


def get_api_key() -> str | None:
    """Get the local Syncthing API key."""
    result = run_syncthing_cli("config", "gui", "apikey", "get")
    return result.stdout.strip() if result.returncode == 0 else None


def api_get(endpoint: str) -> dict | None:
    """Query local Syncthing REST API."""
    import httpx

    api_key = get_api_key()
    if not api_key:
        return None

    headers = {"X-API-Key": api_key}

    # Try HTTPS first, then fall back to HTTP (default is HTTP unless TLS is enabled)
    for scheme in ("https", "http"):
        url = f"{scheme}://localhost:8384{endpoint}"
        try:
            with httpx.Client(timeout=5.0, verify=False) as client:
                response = client.get(url, headers=headers, follow_redirects=True)
                if response.status_code == 200:
                    return response.json()
        except Exception:
            continue
    return None


def get_device_stats() -> dict:
    """Get per-device statistics."""
    return api_get("/rest/stats/device") or {}


def get_config_devices() -> list[dict]:
    """Get full device configuration (with names and addresses)."""
    return api_get("/rest/config/devices") or []


def get_config_folders() -> list[dict]:
    """Get full folder configuration."""
    return api_get("/rest/config/folders") or []


def get_system_status() -> dict | None:
    """Get system status from REST API."""
    return api_get("/rest/system/status")


def get_pending_devices() -> dict:
    """Get pending device pair requests."""
    return api_get("/rest/cluster/pending/devices") or {}


def get_syncthing_version() -> str | None:
    """Get the Syncthing version string."""
    # Try REST API first (more reliable if running)
    version_info = api_get("/rest/system/version")
    if version_info:
        return version_info.get("version")

    # Fall back to CLI
    binary = find_syncthing()
    if not binary:
        return None

    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            # Output is like "syncthing v1.28.0 ..."
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                return parts[1].lstrip("v")
            return result.stdout.strip()
    except Exception:
        pass
    return None


def is_syncthing_running() -> bool:
    """Check if Syncthing is currently running by testing the REST API."""
    status = get_system_status()
    return status is not None


def get_service_status() -> dict:
    """Get Syncthing service/autostart status.

    Returns a dict with:
        - enabled: bool | None - Whether autostart is enabled
        - method: str | None - How it's configured (launchd, systemd, etc.)
        - details: str | None - Additional info
    """
    result = {
        "enabled": None,
        "method": None,
        "details": None,
    }

    if sys.platform == "darwin":
        # macOS: Check launchd plist
        plist_path = Path.home() / "Library/LaunchAgents/syncthing.plist"
        if plist_path.exists():
            result["method"] = "launchd"
            # Check if loaded
            try:
                proc = subprocess.run(
                    ["launchctl", "list", "syncthing"],
                    capture_output=True,
                    text=True,
                )
                result["enabled"] = proc.returncode == 0
                if result["enabled"]:
                    result["details"] = "Loaded via launchd"
                else:
                    result["details"] = "Plist exists but not loaded"
            except Exception:
                result["details"] = "Plist exists"
        else:
            # Also check for homebrew-managed service
            try:
                proc = subprocess.run(
                    ["brew", "services", "list"],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode == 0:
                    for line in proc.stdout.split("\n"):
                        if "syncthing" in line.lower():
                            result["method"] = "homebrew"
                            result["enabled"] = "started" in line.lower()
                            result["details"] = line.strip()
                            break
            except FileNotFoundError:
                pass

    elif sys.platform == "linux":
        # Linux: Check systemd user service
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-enabled", "syncthing"],
                capture_output=True,
                text=True,
            )
            result["method"] = "systemd"
            result["enabled"] = proc.returncode == 0
            result["details"] = proc.stdout.strip() if proc.stdout else None
        except FileNotFoundError:
            pass

    elif sys.platform == "win32":
        # Windows: Check for scheduled task or startup entry
        try:
            # Check Task Scheduler
            proc = subprocess.run(
                ["schtasks", "/Query", "/TN", "Syncthing"],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                result["method"] = "task_scheduler"
                result["enabled"] = True
                result["details"] = "Scheduled task exists"
        except FileNotFoundError:
            pass

        if result["method"] is None:
            # Check startup folder
            startup_path = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
            syncthing_shortcut = startup_path / "Syncthing.lnk"
            if syncthing_shortcut.exists():
                result["method"] = "startup_folder"
                result["enabled"] = True
                result["details"] = "Startup shortcut exists"

    return result
