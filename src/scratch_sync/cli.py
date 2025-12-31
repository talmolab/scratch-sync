"""Command-line interface for scratch-sync."""

import re
import subprocess
import sys
from pathlib import Path

import click

from scratch_sync import syncthing, tailscale, discovery

STIGNORE_TEMPLATE = """\
// Syncthing ignore patterns for scratch folders
// This file is NOT synced between devices

// Python
__pycache__
*.pyc
*.pyo
*.egg-info
.eggs
*.egg
.mypy_cache
.pytest_cache
.ipynb_checkpoints

// Build artifacts
*.so
*.o
*.a
build/
dist/

// Editor/IDE
*.swp
*.swo
*~
.idea/
.vscode/
*.sublime-*

// OS junk
(?d).DS_Store
(?d)Thumbs.db
(?d)desktop.ini
(?d)._*

// Temporary files
*.tmp
*.temp
*.bak
*.log
"""


def get_repo_name(path: Path | None = None) -> str | None:
    """Get the repository name from git remote or directory name."""
    if path is None:
        path = Path.cwd()

    # Try to find .git directory
    git_dir = path / ".git"
    if not git_dir.exists():
        # Walk up
        for parent in path.parents:
            git_dir = parent / ".git"
            if git_dir.exists():
                path = parent
                break
        else:
            return None

    # Try to get remote origin
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=path,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Extract repo name from URL
            # git@github.com:user/repo.git -> repo
            # https://github.com/user/repo.git -> repo
            match = re.search(r"/([^/]+?)(?:\.git)?$", url)
            if match:
                return match.group(1)
    except Exception:
        pass

    # Fall back to directory name
    return path.name


def sanitize_folder_id(name: str) -> str:
    """Sanitize a name for use as a Syncthing folder ID."""
    # Replace problematic characters
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "-", name.lower())
    # Remove consecutive hyphens
    sanitized = re.sub(r"-+", "-", sanitized)
    # Remove leading/trailing hyphens
    return sanitized.strip("-")


@click.group()
@click.version_option()
def main():
    """Sync private scratch/ folders across machines using Syncthing."""
    pass


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--name", "-n", help="Custom name for the sync folder")
def init(path: Path | None, name: str | None):
    """Initialize scratch-sync in a git repository.

    If PATH is not specified, uses the current directory.
    Looks for a scratch/ subdirectory and adds it to Syncthing.
    """
    # Check syncthing is available
    if not syncthing.find_syncthing():
        click.echo("Error: Syncthing not installed. Run the installer first:", err=True)
        click.echo("  curl -LsSf https://raw.githubusercontent.com/talmo/scratch-sync/main/install.sh | sh", err=True)
        sys.exit(1)

    # Determine path
    if path is None:
        path = Path.cwd()

    # Find scratch directory
    scratch_path = path / "scratch"
    if not scratch_path.exists():
        click.echo(f"Creating scratch directory: {scratch_path}")
        scratch_path.mkdir(parents=True)

    # Determine folder name
    if name is None:
        repo_name = get_repo_name(path)
        if repo_name:
            name = repo_name
        else:
            name = path.name

    folder_id = f"scratch-{sanitize_folder_id(name)}"

    # Check if already exists
    if syncthing.folder_exists(folder_id):
        click.echo(f"Folder '{folder_id}' already exists in Syncthing config.")
        click.echo(f"To remove: syncthing cli config folders remove --id {folder_id}")
        sys.exit(1)

    # Add folder
    click.echo(f"Adding folder to Syncthing:")
    click.echo(f"  ID:   {folder_id}")
    click.echo(f"  Path: {scratch_path.resolve()}")

    if not syncthing.add_folder(folder_id, scratch_path.resolve()):
        click.echo("Failed to add folder", err=True)
        sys.exit(1)

    # Add all known devices to this folder
    local_device_id = syncthing.get_device_id()
    for device_id in syncthing.list_devices():
        if device_id != local_device_id:
            syncthing.add_device_to_folder(folder_id, device_id)
            click.echo(f"  Added device: {device_id[:7]}...")

    # Create .stignore if it doesn't exist
    stignore_path = scratch_path / ".stignore"
    if not stignore_path.exists():
        click.echo("Creating default .stignore...")
        stignore_path.write_text(STIGNORE_TEMPLATE)

    # Ensure scratch is in .gitignore
    gitignore_path = path / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if "scratch/" not in content and "/scratch" not in content:
            click.echo("Adding scratch/ to .gitignore...")
            with open(gitignore_path, "a") as f:
                f.write("\n# Local scratch folder (synced via scratch-sync)\nscratch/\n")
    else:
        click.echo("Creating .gitignore with scratch/...")
        gitignore_path.write_text("# Local scratch folder (synced via scratch-sync)\nscratch/\n")

    click.echo()
    click.echo(click.style("Done!", fg="green"))
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Run 'scratch-sync pair' to discover and pair with other devices")
    click.echo("  2. On other devices, run 'scratch-sync init' in the same repo")


@main.command()
@click.option("--timeout", "-t", default=3.0, help="Discovery timeout in seconds")
def pair(timeout: float):
    """Discover and pair with other devices on the Tailscale network."""
    if not tailscale.is_tailscale_running():
        click.echo("Error: Tailscale is not running", err=True)
        sys.exit(1)

    if not syncthing.find_syncthing():
        click.echo("Error: Syncthing not installed", err=True)
        sys.exit(1)

    click.echo("Discovering peers on Tailscale network...")

    # Start discovery server
    try:
        server = discovery.start_discovery_server()
        click.echo(f"Started discovery server on port {discovery.DISCOVERY_PORT}")
    except OSError as e:
        click.echo(f"Warning: Could not start discovery server: {e}", err=True)

    # Find peers
    peers = tailscale.get_online_peers()
    if not peers:
        click.echo("No online peers found on Tailscale network")
        return

    click.echo(f"Found {len(peers)} online peer(s)")
    click.echo()

    # Try to discover each peer
    discovered = []
    for peer in peers:
        click.echo(f"  Checking {peer.hostname} ({peer.tailscale_ip})...", nl=False)
        info = discovery.discover_peer(peer.tailscale_ip, timeout=timeout)
        if info:
            click.echo(click.style(" found!", fg="green"))
            info["tailscale_ip"] = peer.tailscale_ip
            info["tailscale_hostname"] = peer.hostname
            discovered.append(info)
        else:
            click.echo(click.style(" not running scratch-sync", fg="yellow"))

    if not discovered:
        click.echo()
        click.echo("No peers running scratch-sync found.")
        click.echo("Make sure scratch-sync is installed and running on other devices.")
        return

    click.echo()
    click.echo(f"Discovered {len(discovered)} peer(s) running scratch-sync:")

    for info in discovered:
        click.echo(f"  - {info.get('hostname')} ({info.get('tailscale_ip')})")
        click.echo(f"    Device ID: {info.get('syncthing_device_id', 'unknown')[:20]}...")

    click.echo()
    if not click.confirm("Pair with these devices?"):
        return

    # Pair with each
    for info in discovered:
        hostname = info.get("hostname") or info.get("tailscale_hostname")
        if discovery.auto_pair_with_peer(info):
            click.echo(click.style(f"  Paired with {hostname}", fg="green"))
        else:
            click.echo(click.style(f"  Failed to pair with {hostname}", fg="red"))

    click.echo()
    click.echo("Done! Devices are now paired.")
    click.echo("Folders will sync automatically when both devices have the same folder ID.")


@main.command()
def status():
    """Show sync status."""
    if not syncthing.find_syncthing():
        click.echo("Error: Syncthing not installed", err=True)
        sys.exit(1)

    # Get device ID
    try:
        device_id = syncthing.get_device_id()
        click.echo(f"Device ID: {device_id}")
    except Exception as e:
        click.echo(f"Error getting device ID: {e}", err=True)

    # List folders
    folders = syncthing.list_folders()
    scratch_folders = [f for f in folders if f.startswith("scratch-")]

    click.echo()
    click.echo(f"Scratch folders: {len(scratch_folders)}")
    for folder_id in scratch_folders:
        status = syncthing.get_folder_status(folder_id)
        if status:
            state = status.get("state", "unknown")
            click.echo(f"  - {folder_id}: {state}")
        else:
            click.echo(f"  - {folder_id}: unknown")

    # List devices
    devices = syncthing.list_devices()
    local_id = syncthing.get_device_id()
    remote_devices = [d for d in devices if d != local_id]

    connections = syncthing.get_connections()

    click.echo()
    click.echo(f"Connected devices: {len(remote_devices)}")
    for device_id in remote_devices:
        conn = connections.get("connections", {}).get(device_id, {})
        connected = conn.get("connected", False)
        status_str = click.style("connected", fg="green") if connected else click.style("disconnected", fg="yellow")
        click.echo(f"  - {device_id[:15]}... {status_str}")


@main.command("list")
def list_folders():
    """List all scratch-sync managed folders."""
    if not syncthing.find_syncthing():
        click.echo("Error: Syncthing not installed", err=True)
        sys.exit(1)

    folders = syncthing.list_folders()
    scratch_folders = [f for f in folders if f.startswith("scratch-")]

    if not scratch_folders:
        click.echo("No scratch-sync folders configured")
        return

    click.echo("Scratch folders:")
    for folder_id in scratch_folders:
        click.echo(f"  - {folder_id}")


@main.command()
@click.option("--port", "-p", default=discovery.DISCOVERY_PORT, help="Port to run discovery server on")
def serve(port: int):
    """Run the discovery server (for auto-pairing)."""
    if not syncthing.find_syncthing():
        click.echo("Error: Syncthing not installed", err=True)
        sys.exit(1)

    click.echo(f"Starting discovery server on port {port}...")
    click.echo("Press Ctrl+C to stop")

    try:
        from http.server import HTTPServer
        server = HTTPServer(("0.0.0.0", port), discovery.DiscoveryHandler)
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopping...")


if __name__ == "__main__":
    main()
