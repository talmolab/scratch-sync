"""Command-line interface for scratch-sync."""

import re
import subprocess
import sys
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scratch_sync import syncthing, tailscale, discovery

# Rich console for styled output
console = Console()

# Configure rich-click styling
click.rich_click.THEME = "nord-modern"
click.rich_click.TEXT_MARKUP = "rich"
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.HEADER_TEXT = "[bold cyan]scratch-sync[/] - Sync scratch/ folders across machines"
click.rich_click.STYLE_ERRORS_SUGGESTION = "magenta italic"
click.rich_click.ERRORS_SUGGESTION = "Try running [bold]'scratch-sync --help'[/] for more information."

# Group commands for better organization
click.rich_click.COMMAND_GROUPS = {
    "scratch-sync": [
        {
            "name": "Setup",
            "commands": ["init", "pair"],
        },
        {
            "name": "Monitoring",
            "commands": ["status", "list"],
        },
        {
            "name": "Advanced",
            "commands": ["serve"],
        },
    ]
}

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
@click.version_option(prog_name="scratch-sync")
def main():
    """Sync private [bold cyan]scratch/[/] folders across machines using [bold]Syncthing[/] over [bold]Tailscale[/].

    [dim]scratch-sync helps you keep your local scratch directories synchronized
    across all your development machines on a private Tailscale network.[/]

    [bold]Quick start:[/]
      1. Run [cyan]scratch-sync init[/] in a git repository
      2. Run [cyan]scratch-sync pair[/] to discover other devices
      3. Repeat on your other machines
    """
    pass


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False, metavar="[PATH]")
@click.option("--name", "-n", help="Custom name for the sync folder [dim](defaults to repo name)[/]")
def init(path: Path | None, name: str | None):
    """Initialize scratch-sync in a git repository.

    Sets up a [bold cyan]scratch/[/] folder for syncing in the specified directory
    (or current directory if not specified).

    [bold]What this does:[/]
      • Creates [cyan]scratch/[/] directory if it doesn't exist
      • Adds the folder to Syncthing with ID [dim]scratch-<repo-name>[/]
      • Creates a default [dim].stignore[/] file
      • Adds [cyan]scratch/[/] to [dim].gitignore[/]
    """
    # Check syncthing is available
    if not syncthing.find_syncthing():
        console.print("[red]Error:[/] Syncthing not installed. Run the installer first:")
        console.print("  [cyan]curl -LsSf https://scratch.tlab.sh/install.sh | sh[/]")
        sys.exit(1)

    # Determine path
    if path is None:
        path = Path.cwd()

    # Find scratch directory
    scratch_path = path / "scratch"
    if not scratch_path.exists():
        console.print(f"[cyan]Creating[/] scratch directory: [bold]{scratch_path}[/]")
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
        console.print(f"[yellow]Warning:[/] Folder [cyan]{folder_id}[/] already exists in Syncthing config.")
        console.print(f"[dim]To remove: syncthing cli config folders remove --id {folder_id}[/]")
        sys.exit(1)

    # Add folder
    console.print("[bold]Adding folder to Syncthing:[/]")
    console.print(f"  [dim]ID:[/]   [cyan]{folder_id}[/]")
    console.print(f"  [dim]Path:[/] [cyan]{scratch_path.resolve()}[/]")

    if not syncthing.add_folder(folder_id, scratch_path.resolve()):
        console.print("[red]Failed to add folder[/]")
        sys.exit(1)

    # Add all known devices to this folder
    local_device_id = syncthing.get_device_id()
    for device_id in syncthing.list_devices():
        if device_id != local_device_id:
            syncthing.add_device_to_folder(folder_id, device_id)
            console.print(f"  [green]Added device:[/] [dim]{device_id[:7]}...[/]")

    # Create .stignore if it doesn't exist
    stignore_path = scratch_path / ".stignore"
    if not stignore_path.exists():
        console.print("[cyan]Creating[/] default .stignore...")
        stignore_path.write_text(STIGNORE_TEMPLATE)

    # Ensure scratch is in .gitignore
    gitignore_path = path / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if "scratch/" not in content and "/scratch" not in content:
            console.print("[cyan]Adding[/] scratch/ to .gitignore...")
            with open(gitignore_path, "a") as f:
                f.write("\n# Local scratch folder (synced via scratch-sync)\nscratch/\n")
    else:
        console.print("[cyan]Creating[/] .gitignore with scratch/...")
        gitignore_path.write_text("# Local scratch folder (synced via scratch-sync)\nscratch/\n")

    console.print()
    console.print("[bold green]Done![/]")
    console.print()
    console.print("[bold]Next steps:[/]")
    console.print("  1. Run [cyan]scratch-sync pair[/] to discover and pair with other devices")
    console.print("  2. On other devices, run [cyan]scratch-sync init[/] in the same repo")


@main.command()
@click.option("--timeout", "-t", default=3.0, show_default=True, help="Discovery timeout in seconds")
def pair(timeout: float):
    """Discover and pair with other devices on the Tailscale network.

    Scans your [bold]Tailscale[/] network for other machines running scratch-sync
    and automatically pairs them for folder synchronization.

    [bold]Requirements:[/]
      • Tailscale must be running and connected
      • Other devices should have scratch-sync installed
    """
    if not tailscale.is_tailscale_running():
        console.print("[red]Error:[/] Tailscale is not running")
        sys.exit(1)

    if not syncthing.find_syncthing():
        console.print("[red]Error:[/] Syncthing not installed")
        sys.exit(1)

    console.print("[bold]Discovering peers on Tailscale network...[/]")

    # Start discovery server
    try:
        server = discovery.start_discovery_server()
        console.print(f"[dim]Started discovery server on port {discovery.DISCOVERY_PORT}[/]")
    except OSError as e:
        console.print(f"[yellow]Warning:[/] Could not start discovery server: {e}")

    # Find peers
    peers = tailscale.get_online_peers()
    if not peers:
        console.print("[dim]No online peers found on Tailscale network[/]")
        return

    console.print(f"Found [bold]{len(peers)}[/] online peer(s)")
    console.print()

    # Try to discover each peer
    discovered = []
    for peer in peers:
        console.print(f"  Checking [cyan]{peer.hostname}[/] ({peer.tailscale_ip})...", end="")
        info = discovery.discover_peer(peer.tailscale_ip, timeout=timeout)
        if info:
            console.print(" [green]found![/]")
            info["tailscale_ip"] = peer.tailscale_ip
            info["tailscale_hostname"] = peer.hostname
            discovered.append(info)
        else:
            console.print(" [yellow]not running scratch-sync[/]")

    if not discovered:
        console.print()
        console.print("[dim]No peers running scratch-sync found.[/]")
        console.print("[dim]Make sure scratch-sync is installed and running on other devices.[/]")
        return

    console.print()
    console.print(f"[bold]Discovered {len(discovered)} peer(s) running scratch-sync:[/]")

    for info in discovered:
        console.print(f"  [cyan]•[/] {info.get('hostname')} [dim]({info.get('tailscale_ip')})[/]")
        console.print(f"    [dim]Device ID: {info.get('syncthing_device_id', 'unknown')[:20]}...[/]")

    console.print()
    if not click.confirm("Pair with these devices?"):
        return

    # Pair with each
    for info in discovered:
        hostname = info.get("hostname") or info.get("tailscale_hostname")
        if discovery.auto_pair_with_peer(info):
            console.print(f"  [green]Paired with {hostname}[/]")
        else:
            console.print(f"  [red]Failed to pair with {hostname}[/]")

    console.print()
    console.print("[bold green]Done![/] Devices are now paired.")
    console.print("[dim]Folders will sync automatically when both devices have the same folder ID.[/]")


def _get_state_style(state: str) -> str:
    """Get rich style for a sync state."""
    state_styles = {
        "idle": "green",
        "scanning": "yellow",
        "syncing": "cyan",
        "error": "red",
        "unknown": "dim",
    }
    return state_styles.get(state, "dim")


@main.command()
def status():
    """Show current sync status.

    Displays information about:
      • Your device ID
      • All [cyan]scratch-*[/] folders and their sync state
      • Connected devices and their status
    """
    if not syncthing.find_syncthing():
        console.print("[red]Error:[/] Syncthing not installed", style="red")
        sys.exit(1)

    # Get device ID
    try:
        device_id = syncthing.get_device_id()
        console.print(f"[bold]Device ID:[/] [dim]{device_id}[/]")
    except Exception as e:
        console.print(f"[red]Error getting device ID:[/] {e}")

    # List folders
    folders = syncthing.list_folders()
    scratch_folders = [f for f in folders if f.startswith("scratch-")]

    console.print()
    if scratch_folders:
        folder_table = Table(title="Scratch Folders", box=None, padding=(0, 2))
        folder_table.add_column("Folder ID", style="cyan")
        folder_table.add_column("Status")

        for folder_id in scratch_folders:
            folder_status = syncthing.get_folder_status(folder_id)
            if folder_status:
                state = folder_status.get("state", "unknown")
                style = _get_state_style(state)
                folder_table.add_row(folder_id, f"[{style}]{state}[/]")
            else:
                folder_table.add_row(folder_id, "[dim]unknown[/]")

        console.print(folder_table)
    else:
        console.print("[dim]No scratch folders configured[/]")

    # List devices
    devices = syncthing.list_devices()
    local_id = syncthing.get_device_id()
    remote_devices = [d for d in devices if d != local_id]

    connections = syncthing.get_connections()

    console.print()
    if remote_devices:
        device_table = Table(title="Connected Devices", box=None, padding=(0, 2))
        device_table.add_column("Device ID", style="dim")
        device_table.add_column("Status")

        for device_id in remote_devices:
            conn = connections.get("connections", {}).get(device_id, {})
            connected = conn.get("connected", False)
            status_str = "[green]connected[/]" if connected else "[yellow]disconnected[/]"
            device_table.add_row(f"{device_id[:20]}...", status_str)

        console.print(device_table)
    else:
        console.print("[dim]No remote devices configured[/]")


@main.command("list")
def list_folders():
    """List all scratch-sync managed folders.

    Shows all Syncthing folders with IDs starting with [cyan]scratch-[/].
    """
    if not syncthing.find_syncthing():
        console.print("[red]Error:[/] Syncthing not installed")
        sys.exit(1)

    folders = syncthing.list_folders()
    scratch_folders = [f for f in folders if f.startswith("scratch-")]

    if not scratch_folders:
        console.print("[dim]No scratch-sync folders configured[/]")
        return

    console.print("[bold]Scratch folders:[/]")
    for folder_id in scratch_folders:
        console.print(f"  [cyan]•[/] {folder_id}")


@main.command()
@click.option("--port", "-p", default=discovery.DISCOVERY_PORT, show_default=True, help="Port to run discovery server on")
def serve(port: int):
    """Run the discovery server for auto-pairing.

    Starts an HTTP server that responds to discovery requests from other
    scratch-sync clients on the network. This enables automatic device pairing.

    [dim]This is typically run automatically during [bold]scratch-sync pair[/].[/]
    """
    if not syncthing.find_syncthing():
        console.print("[red]Error:[/] Syncthing not installed")
        sys.exit(1)

    console.print(f"[bold]Starting discovery server on port [cyan]{port}[/]...[/]")
    console.print("[dim]Press Ctrl+C to stop[/]")

    try:
        from http.server import HTTPServer
        server = HTTPServer(("0.0.0.0", port), discovery.DiscoveryHandler)
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping...[/]")


if __name__ == "__main__":
    main()
