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
    result = run_syncthing_cli("show", "folder-status", folder_id)
    if result.returncode != 0:
        return None

    return json.loads(result.stdout)


def get_connections() -> dict:
    """Get connection status for all devices."""
    result = run_syncthing_cli("show", "connections")
    if result.returncode != 0:
        return {}

    return json.loads(result.stdout)
